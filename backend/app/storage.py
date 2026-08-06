"""持久化层：配置（JSON）、结果（JSONL，append-only）、密钥（哈希化的访问码与 JWT secret）。"""
import asyncio
import json
import os
from collections import deque
from datetime import datetime
from pathlib import Path

from app.models import CheckResult, Paginated, ResultFilter, Target, new_id
from app.timeutil import hhmm_in_range


def atomic_write(path: Path, text: str) -> None:
    """临时文件 + os.replace，避免写一半留下损坏文件。"""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


class ConfigStore:
    """检查目标配置，存于 data/config.json。"""

    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.path = data_dir / "config.json"
        self._lock = asyncio.Lock()
        self.targets: dict[str, Target] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            self._persist()
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            self._persist()
            return
        self.targets = {}
        for item in raw.get("check_targets", []):
            try:
                t = Target.model_validate(item)
                self.targets[t.id] = t
            except Exception:
                continue  # 单条损坏不拖垮整体

    def _persist(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "last_updated": now_iso(),
            "check_targets": [t.model_dump(mode="json") for t in self.targets.values()],
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


class ResultStore:
    """检查结果，存于 data/results.jsonl（每行一个 JSON）。追加写，超上限截断最旧。"""

    def __init__(self, path: Path, max_records: int):
        self.path = path
        self.max_records = max_records
        self._lock = asyncio.Lock()
        self._results: deque[CheckResult] = deque()
        self._subscribers: set[asyncio.Queue] = set()
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        with self.path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    self._results.append(CheckResult.model_validate_json(line))
                except Exception:
                    continue
        while len(self._results) > self.max_records:
            self._results.popleft()

    def _persist_all(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="utf-8") as f:
            for r in self._results:
                f.write(r.model_dump_json() + "\n")

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
        await self._broadcast(result)

    async def query(self, f: ResultFilter) -> Paginated:
        def matches(r: CheckResult) -> bool:
            if f.status not in (None, "all") and r.status != f.status:
                return False
            if f.ip and f.ip not in r.ip:
                return False
            if f.target_id and r.target_id != f.target_id:
                return False
            if f.date and r.checked_at.astimezone().strftime("%Y-%m-%d") != f.date:
                return False
            if f.time_start and f.time_end:
                hhmm = r.checked_at.astimezone().strftime("%H:%M")
                if not hhmm_in_range(hhmm, [{"start": f.time_start, "end": f.time_end}]):
                    return False
            return True

        async with self._lock:
            all_results = list(self._results)
        filtered = [r for r in reversed(all_results) if matches(r)]
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
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            self.jwt_secret = raw.get("jwt_secret", "")
            self.access_code_hash = raw.get("access_code_hash", "")
        except (json.JSONDecodeError, OSError):
            pass

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"jwt_secret": self.jwt_secret, "access_code_hash": self.access_code_hash}
        atomic_write(self.path, json.dumps(payload, ensure_ascii=False, indent=2))
