"""持久化层：配置（JSON）、结果（JSONL，append-only）、密钥（哈希化的访问码与 JWT secret）。"""
import asyncio
import json
import logging
import os
from collections import deque
from datetime import datetime, timedelta
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any

from app.models import (
    AppSettings,
    CheckResult,
    Paginated,
    ResultFilter,
    S3Config,
    Target,
    WebhookConfig,
    new_id,
)
from app.s3_storage import S3Storage
from app.timeutil import hhmm_in_range

logger = logging.getLogger(__name__)


def atomic_write(path: Path, text: str) -> None:
    """临时文件 + os.replace，避免写一半留下损坏文件。"""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def ip_matches(pattern: str, ip: str) -> bool:
    """IP 筛选：含 * / ? 时按通配符全匹配，否则保留原来的子串匹配。"""
    if "*" in pattern or "?" in pattern:
        return fnmatchcase(ip, pattern)
    return pattern in ip


class ConfigStore:
    """检查目标配置，存于 data/config.json。"""

    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.path = data_dir / "config.json"
        self._lock = asyncio.Lock()
        self.targets: dict[str, Target] = {}
        self._webhook = WebhookConfig()
        self._app = AppSettings()
        self._s3 = S3Config()
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            self._persist()
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            logger.error(
                "Failed to parse config.json (%s): %s; resetting to defaults",
                type(e).__name__,
                e,
            )
            self._persist()
            return
        self.targets = {}
        backfill = False
        for item in raw.get("check_targets", []):
            try:
                t = Target.model_validate(item)
                self.targets[t.id] = t
                if "notify_enabled" not in item:
                    backfill = True
            except Exception as e:
                # 单条损坏不拖垮整体，但记录 error 便于排查
                tid = item.get("id", "<no id>") if isinstance(item, dict) else "<non-dict>"
                logger.error(
                    "Invalid check target in config.json skipped (id=%s): %s",
                    tid,
                    e,
                )
                continue
        raw_webhook = raw.get("webhook")
        if isinstance(raw_webhook, dict):
            try:
                self._webhook = WebhookConfig.model_validate(raw_webhook)
            except Exception as e:
                logger.error("Invalid webhook config in config.json: %s", e)
        raw_app = raw.get("app")
        if isinstance(raw_app, dict):
            try:
                self._app = AppSettings.model_validate(raw_app)
            except Exception as e:
                logger.error("Invalid app settings in config.json: %s", e)
        raw_s3 = raw.get("s3")
        if isinstance(raw_s3, dict):
            try:
                self._s3 = S3Config.model_validate(raw_s3)
            except Exception as e:
                logger.error("Invalid s3 config in config.json: %s", e)
        if backfill:
            # 旧版配置缺少 notify_enabled，补默认 true 并写回，保证字段齐全
            self._persist()

    def _persist(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "last_updated": now_iso(),
            "check_targets": [t.model_dump(mode="json") for t in self.targets.values()],
            "webhook": self._webhook.model_dump(mode="json"),
            "app": self._app.model_dump(mode="json"),
            "s3": self._s3.model_dump(mode="json"),
        }
        atomic_write(self.path, json.dumps(payload, ensure_ascii=False, indent=2))

    async def save(self) -> None:
        async with self._lock:
            self._persist()

    def file_mtime(self) -> float | None:
        """config.json 的修改时间，用于外部编辑热检测。"""
        try:
            return self.path.stat().st_mtime
        except OSError:
            return None

    async def reload(self) -> None:
        """重新从磁盘加载配置（保留未持久化变更时的容错）。"""
        async with self._lock:
            self._load()

    async def list_targets(self) -> list[Target]:
        return list(self.targets.values())

    async def get_target(self, target_id: str) -> Target | None:
        return self.targets.get(target_id)

    async def upsert_target(self, target: Target) -> None:
        async with self._lock:
            self.targets[target.id] = target
            self._persist()

    async def delete_target(self, target_id: str) -> bool:
        async with self._lock:
            if target_id not in self.targets:
                return False
            del self.targets[target_id]
            self._persist()
            return True

    @staticmethod
    def new_target_id(existing: dict[str, Target]) -> str:
        while True:
            candidate = new_id()
            if candidate not in existing:
                return candidate

    async def get_webhook_config(self) -> WebhookConfig:
        return self._webhook

    async def update_webhook_config(self, cfg: WebhookConfig) -> WebhookConfig:
        async with self._lock:
            self._webhook = cfg
            self._persist()
        return self._webhook

    async def get_app_settings(self) -> AppSettings:
        return self._app

    async def update_app_settings(self, cfg: AppSettings) -> AppSettings:
        async with self._lock:
            self._app = cfg
            self._persist()
        return self._app

    async def get_s3_config(self) -> S3Config:
        return self._s3

    async def update_s3_config(self, cfg: S3Config) -> S3Config:
        async with self._lock:
            self._s3 = cfg
            self._persist()
        logger.info(
            "S3 config updated: enabled=%s endpoint=%s bucket=%s region=%s datapath=%s",
            cfg.enabled,
            cfg.endpoint,
            cfg.bucket,
            cfg.region,
            cfg.datapath,
        )
        return self._s3


class ResultStore:
    """检查结果，存于 data/results.jsonl（每行一个 JSON）。追加写，超上限截断最旧。

    storage_mode=local 仅本地；=both 本地 + S3 双写；=s3 主存 S3（本地文件作兜底缓冲），
    启动时从 S3 加载并合并本地文件补缺。S3 按天对象 datapath/results/YYYY-MM-DD.jsonl
    永久保留（不随本地裁剪丢失）。
    """

    def __init__(
        self,
        path: Path,
        max_records: int,
        storage_mode: str = "local",
        s3: S3Storage | None = None,
    ):
        self.path = path
        self.max_records = max_records
        self._storage_mode = storage_mode
        self._s3 = s3
        self._s3_prefix = self._s3.cfg.datapath.rstrip("/") + "/results/" if s3 else ""
        self._lock = asyncio.Lock()
        self._results: deque[CheckResult] = deque()
        self._seen_ids: set[str] = set()
        self._subscribers: set[asyncio.Queue] = set()
        self._load()

    def _load(self) -> None:
        merge_local = False
        if self._s3 is not None and self._storage_mode == "s3":
            try:
                self._load_from_s3()
                merge_local = True
            except Exception as e:  # noqa: BLE001
                logger.warning("S3 results load failed: %s; falling back to local file", e)
        self._load_local(merge=merge_local)
        while len(self._results) > self.max_records:
            self._results.popleft()

    def _load_from_s3(self) -> None:
        for object_name in self._s3.list_objects(self._s3_prefix):
            data = self._s3.get_data(object_name)
            if not data:
                continue
            for line in data.decode("utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    r = CheckResult.model_validate_json(line)
                except Exception:
                    continue
                self._seen_ids.add(r.id)
                self._results.append(r)
        logger.info("Loaded %d results from S3", len(self._results))

    def _load_local(self, merge: bool = False) -> None:
        if not self.path.exists():
            return
        with self.path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = CheckResult.model_validate_json(line)
                except Exception:
                    continue
                if merge and r.id in self._seen_ids:
                    continue
                self._results.append(r)

    def set_s3_mode(
        self, storage_mode: str, s3_cfg: S3Config | None, access_id: str, access_key: str
    ) -> None:
        """热更新存储模式与 S3 客户端（配置变更后由 watchdog 调用）。"""
        if (
            storage_mode == "local"
            or s3_cfg is None
            or not s3_cfg.enabled
            or not (access_id and access_key)
        ):
            self._s3 = None
            self._storage_mode = storage_mode
        else:
            self._s3 = S3Storage(s3_cfg, access_id, access_key)
            self._storage_mode = storage_mode
        self._s3_prefix = self._s3.cfg.datapath.rstrip("/") + "/results/" if self._s3 else ""
        logger.info(
            "Result storage mode=%s s3=%s",
            self._storage_mode,
            "enabled" if self._s3 else "disabled",
        )

    def _persist_all(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="utf-8") as f:
            for r in self._results:
                f.write(r.model_dump_json() + "\n")

    def resize(self, max_records: int) -> None:
        """调整保留上限并立即裁剪超出部分（同步调用，内部无 await）。"""
        if max_records == self.max_records:
            return
        self.max_records = max_records
        excess = len(self._results) - self.max_records
        if excess > 0:
            for _ in range(excess):
                self._results.popleft()
            self._persist_all()

    async def append(self, result: CheckResult) -> None:
        trimmed = False
        async with self._lock:
            self._results.append(result)
            if len(self._results) > self.max_records:
                excess = len(self._results) - self.max_records
                for _ in range(excess):
                    self._results.popleft()
                trimmed = True
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as f:
                f.write(result.model_dump_json() + "\n")
            if trimmed:
                self._persist_all()
            if self._s3 is not None:
                try:
                    await asyncio.to_thread(
                        self._sync_to_s3,
                        result.checked_at.astimezone().strftime("%Y-%m-%d"),
                    )
                except Exception as e:  # noqa: BLE001
                    logger.error(
                        "S3 results sync failed: %s; results kept in local file", e
                    )
        await self._broadcast(result)

    def _sync_to_s3(self, date_str: str) -> None:
        """把指定日期当天的记录全量合并上传为 S3 对象（按 id 去重，永久保留）。

        先拉取已有对象再并入新行，避免本地裁剪导致 S3 历史丢失。
        """
        object_name = f"{self._s3_prefix}{date_str}.jsonl"
        merged: dict[str, str] = {}
        try:
            data = self._s3.get_data(object_name)
        except Exception as e:  # noqa: BLE001
            logger.warning("Failed to fetch existing S3 object %s: %s", object_name, e)
            data = None
        if data:
            for line in data.decode("utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    merged[CheckResult.model_validate_json(line).id] = line
                except Exception:
                    continue
        for r in self._results:
            if r.checked_at.astimezone().strftime("%Y-%m-%d") == date_str:
                merged[r.id] = r.model_dump_json()
        payload = "".join(v + "\n" for v in merged.values())
        if payload:
            self._s3.put_data(object_name, payload.encode("utf-8"))
        logger.debug(
            "Synced %d records to s3://%s/%s", len(merged), self._s3.bucket, object_name
        )

    @staticmethod
    def _matches(f: ResultFilter, r: CheckResult) -> bool:
        # status / target_id 支持逗号分隔多值（前端多选）
        if f.status:
            statuses = {s for s in f.status.split(",") if s and s != "all"}
            if statuses and r.status not in statuses:
                return False
        if f.ip and not ip_matches(f.ip, r.ip):
            return False
        # target_name 支持逗号分隔多值（前端多选），匹配目标名称或 IP（无名称目标以 IP 作为筛选值）
        if f.target_name:
            names = {s for s in f.target_name.split(",") if s}
            if names and r.target_name not in names and r.ip not in names:
                return False
        if f.target_id:
            ids = {s for s in f.target_id.split(",") if s}
            if ids and r.target_id not in ids:
                return False
        if f.date and r.checked_at.astimezone().strftime("%Y-%m-%d") != f.date:
            return False
        if f.time_start and f.time_end:
            hhmm = r.checked_at.astimezone().strftime("%H:%M")
            if not hhmm_in_range(hhmm, [{"start": f.time_start, "end": f.time_end}]):
                return False
        # 完整时间范围（本地时区比较），起止可跨日
        checked = r.checked_at.astimezone()
        if f.start_at:
            try:
                start_dt = datetime.fromisoformat(f.start_at)
                if start_dt.tzinfo is None:
                    start_dt = start_dt.astimezone()  # 前端传本地时间，按本地时区解释
                if checked < start_dt:
                    return False
            except ValueError:
                pass
        if f.end_at:
            try:
                end_dt = datetime.fromisoformat(f.end_at)
                if end_dt.tzinfo is None:
                    end_dt = end_dt.astimezone()
                if checked > end_dt:
                    return False
            except ValueError:
                pass
        return True

    async def query(self, f: ResultFilter) -> Paginated:
        async with self._lock:
            all_results = list(self._results)
        filtered = [r for r in reversed(all_results) if self._matches(f, r)]
        total = len(filtered)
        start = (f.page - 1) * f.page_size
        page_items = filtered[start : start + f.page_size]
        return Paginated(
            results=page_items,
            total=total,
            page=f.page,
            page_size=f.page_size,
            pages=(total + f.page_size - 1) // f.page_size if total else 0,
        )

    async def export_all(self, f: ResultFilter) -> list[CheckResult]:
        """与 query 相同的过滤条件，返回全量结果（不分页、按时间倒序）。"""
        async with self._lock:
            all_results = list(self._results)
        return [r for r in reversed(all_results) if self._matches(f, r)]

    async def trend(self, hours: int = 24) -> list[dict[str, Any]]:
        """按小时聚合最近 N 小时的检查结果（本地时区，空时段也补齐）。"""
        async with self._lock:
            results = list(self._results)
        now = datetime.now().astimezone()
        base = now.replace(minute=0, second=0, microsecond=0)
        cutoff = base - timedelta(hours=hours - 1)
        buckets: dict[str, dict[str, Any]] = {}
        for i in range(hours):
            key = (cutoff + timedelta(hours=i)).strftime("%Y-%m-%dT%H:00")
            buckets[key] = {
                "bucket": key,
                "total": 0,
                "success": 0,
                "fail": 0,
                "timeout": 0,
                "error": 0,
                "avg_latency_ms": None,
            }
        lat: dict[str, list[float]] = {}
        for r in results:
            t = r.checked_at.astimezone()
            if t < cutoff:
                continue
            b = buckets.get(t.strftime("%Y-%m-%dT%H:00"))
            if b is None:
                continue
            b["total"] += 1
            b[r.status] += 1
            if r.latency_ms is not None:
                lat.setdefault(b["bucket"], []).append(r.latency_ms)
        for key, b in buckets.items():
            vals = lat.get(key)
            if vals:
                b["avg_latency_ms"] = round(sum(vals) / len(vals), 1)
        return list(buckets.values())

    async def latest_per_target(self, target_ids: list[str]) -> dict[str, CheckResult]:
        """返回每个目标最近一条结果（按时间倒序找首个）。"""
        async with self._lock:
            wanted = set(target_ids)
            latest: dict[str, CheckResult] = {}
            for r in reversed(self._results):
                if r.target_id in wanted and r.target_id not in latest:
                    latest[r.target_id] = r
            return latest

    async def recent(self, limit: int = 20) -> list[CheckResult]:
        async with self._lock:
            return list(self._results)[-limit:][::-1]

    async def count_by_status(self, window: int = 50) -> dict[str, int]:
        async with self._lock:
            recent_50 = list(self._results)[-window:]
        counts: dict[str, int] = {"success": 0, "fail": 0, "timeout": 0, "error": 0}
        for r in recent_50:
            if r.status in counts:
                counts[r.status] += 1
        return counts

    # --- SSE 广播 ---
    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=100)
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subscribers.discard(q)

    async def _broadcast(self, result: CheckResult) -> None:
        for q in list(self._subscribers):
            try:
                q.put_nowait(result)
            except asyncio.QueueFull:
                pass  # 积压时丢弃，客户端重连即可


class SecretsStore:
    """密钥与访问码哈希，存于 data/secrets.json。明文访问码不落盘。"""

    def __init__(self, data_dir: Path):
        self.path = data_dir / "secrets.json"
        self.jwt_secret: str = ""
        self.access_code_hash: str = ""
        self.s3_access_id: str = ""
        self.s3_access_key: str = ""
        self.api_token: str = ""
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            self.jwt_secret = raw.get("jwt_secret", "")
            self.access_code_hash = raw.get("access_code_hash", "")
            self.s3_access_id = raw.get("s3_access_id", "")
            self.s3_access_key = raw.get("s3_access_key", "")
            self.api_token = raw.get("api_token", "")
        except (json.JSONDecodeError, OSError):
            pass

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "jwt_secret": self.jwt_secret,
            "access_code_hash": self.access_code_hash,
            "s3_access_id": self.s3_access_id,
            "s3_access_key": self.s3_access_key,
            "api_token": self.api_token,
        }
        atomic_write(self.path, json.dumps(payload, ensure_ascii=False, indent=2))

    def set_s3_credentials(self, access_id: str | None, access_key: str | None) -> None:
        """更新 S3 凭据并落盘；None 表示该字段保持不变。日志只记录是否设置，不输出明文。"""
        if access_id is not None:
            self.s3_access_id = access_id
        if access_key is not None:
            self.s3_access_key = access_key
        self.save()
        logger.info(
            "S3 credentials updated (access_id set=%s, access_key set=%s)",
            access_id is not None,
            access_key is not None,
        )

    def set_api_token(self, token: str | None) -> str | None:
        """设置 API Token 并落盘；None = 清空禁用。返回当前 token（无则 None）。"""
        self.api_token = token or ""
        self.save()
        return self.api_token or None
