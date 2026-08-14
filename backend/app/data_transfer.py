"""数据导入/导出/备份核心逻辑：把可导入数据打包为 zip（config + results + logs，
不含密钥），以及导出包校验与导入合并。HTTP 层在 api/data.py。

语义约定（与用户确认）：
- 导出/备份不含 secrets.json 与 backups/（密钥永不落包）
- 导入：检查记录追加（按 id 去重）、检查目标按 id 合并（覆盖/新增）、设置逐键合并
- 日志不支持导入（导出包含，导入时忽略）
"""
import json
import logging
import re
import zipfile
from datetime import datetime
from pathlib import Path

from app.logging_setup import apply_level
from app.models import AppSettings, CheckResult, S3Config, Target, WebhookConfig
from app.storage import now_iso

logger = logging.getLogger(__name__)

# 导出包标识：导入时据此识别「本应用导出的数据包」
MANIFEST_APP = "connection-checker"
MANIFEST_SCHEMA = 1
# 备份文件名：默认 backup-YYYYMMDD-HHMMSS.zip，支持重命名为任意安全 .zip 文件名
# （不以 . 或路径分隔符开头、不含 / 与 \、以 .zip 结尾，防路径穿越）
BACKUP_NAME_RE = re.compile(r"^[^./\\][^/\\]{0,200}\.zip$")


def backup_dir(data_dir: Path) -> Path:
    d = data_dir / "backups"
    d.mkdir(parents=True, exist_ok=True)
    return d


def build_package(zip_path: Path, data_dir: Path) -> int:
    """把可导入数据打包为 zip：manifest + config.json + results.jsonl + logs/*.log。

    不含 secrets.json 与 backups/；日志文件被占用时跳过不中断打包。
    返回打包的文件数（不含 manifest）。
    """
    manifest = {"app": MANIFEST_APP, "schema": MANIFEST_SCHEMA, "created_at": now_iso()}
    count = 0
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        for name in ("config.json", "results.jsonl"):
            p = data_dir / name
            if p.is_file():
                zf.write(p, name)
                count += 1
                logger.debug("Packaged %s", name)
        logs_dir = data_dir / "logs"
        if logs_dir.is_dir():
            for f in sorted(logs_dir.glob("*.log")):
                try:
                    zf.write(f, f"logs/{f.name}")
                    count += 1
                    logger.debug("Packaged logs/%s", f.name)
                except OSError as e:
                    # 日志文件被占用（Windows 文件锁）等场景：跳过不中断打包
                    logger.warning("Log file skipped while packaging (%s): %s", f.name, e)
    return count


def validate_package(zip_path: Path) -> None:
    """校验 zip 是否本应用导出的数据包（manifest 匹配）。不匹配抛 ValueError。"""
    try:
        with zipfile.ZipFile(zip_path) as zf:
            if "manifest.json" not in zf.namelist():
                raise ValueError("zip 中缺少 manifest.json，不是本应用导出的数据包")
            manifest = json.loads(zf.read("manifest.json"))
    except zipfile.BadZipFile as e:
        raise ValueError("文件不是有效的 zip 数据包") from e
    except (json.JSONDecodeError, KeyError) as e:
        raise ValueError("数据包 manifest 损坏") from e
    if manifest.get("app") != MANIFEST_APP or manifest.get("schema") != MANIFEST_SCHEMA:
        raise ValueError("数据包与应用不匹配或版本不受支持")


def _merge_section(model_cls, current, incoming: dict):
    """逐键合并：incoming 中当前模型存在的键覆盖，其余键保持当前值。

    保证旧版本导出的包（缺新字段）不会回退新版本引入的配置项。
    """
    merged = {
        **current.model_dump(),
        **{k: v for k, v in incoming.items() if k in model_cls.model_fields},
    }
    return model_cls.model_validate(merged)


async def apply_import(
    request, zip_path: Path, *, records: bool, targets: bool, settings: bool
) -> dict:
    """执行导入（zip 已通过校验）。records/targets/settings 至少一项为 True。

    返回统计 {"records": int, "targets": int, "settings": bool}。
    导入后内存状态即时更新；S3 模式等其余变更由 config watchdog 5s 内热更新。
    """
    store = request.app.state.config_store
    result_store = request.app.state.result_store
    stats = {"records": 0, "targets": 0, "settings": False}
    with zipfile.ZipFile(zip_path) as zf:
        names = set(zf.namelist())
        zip_cfg: dict = {}
        if (targets or settings) and "config.json" in names:
            zip_cfg = json.loads(zf.read("config.json"))
        if records and "results.jsonl" in names:
            imported: list[CheckResult] = []
            with zf.open("results.jsonl") as f:
                for line in f:
                    try:
                        imported.append(CheckResult.model_validate_json(line))
                    except Exception as e:  # noqa: BLE001
                        logger.warning("Imported result line skipped: %s", e)
            stats["records"] = await result_store.import_records(imported)
            logger.info(
                "Check records imported: %d/%d", stats["records"], len(imported)
            )
        if targets and "config.json" in names:
            new_targets: list[Target] = []
            for item in zip_cfg.get("check_targets", []):
                try:
                    new_targets.append(Target.model_validate(item))
                except Exception as e:  # noqa: BLE001
                    logger.warning("Imported target skipped: %s", e)
            for t in new_targets:
                store.targets[t.id] = t
            stats["targets"] = len(new_targets)
            await store.save()
            logger.info("Check targets imported: %d (merged by id)", len(new_targets))
        if settings and "config.json" in names:
            app = _merge_section(
                AppSettings, await store.get_app_settings(), zip_cfg.get("app", {})
            )
            webhook = _merge_section(
                WebhookConfig, await store.get_webhook_config(), zip_cfg.get("webhook", {})
            )
            s3 = _merge_section(
                S3Config, await store.get_s3_config(), zip_cfg.get("s3", {})
            )
            secrets = request.app.state.secrets_store
            if s3.enabled and not bool(secrets.s3_access_id and secrets.s3_access_key):
                # 导入的包不含凭据：无凭据时禁用 S3，避免热切换后连接持续失败
                s3 = s3.model_copy(update={"enabled": False})
                logger.warning(
                    "S3 enabled in imported settings but credentials missing; s3 disabled"
                )
            await store.update_app_settings(app)
            await store.update_webhook_config(webhook)
            await store.update_s3_config(s3)
            # 立即生效的部分：结果保留上限（同步方法，勿 await）与日志级别
            result_store.resize(app.result_max_records)
            apply_level(app.log_level)
            stats["settings"] = True
            logger.info("Settings imported (app/webhook/s3, merged per key)")
    return stats


def create_backup(data_dir: Path) -> Path:
    """创建备份 zip（内容与导出相同，不含密钥）。返回备份文件路径。"""
    name = f"backup-{datetime.now().strftime('%Y%m%d-%H%M%S')}.zip"
    path = backup_dir(data_dir) / name
    build_package(path, data_dir)
    return path


def list_backups(data_dir: Path) -> list[dict]:
    """备份列表（新→旧）：name / size / created_at（本地时间 ISO）。"""
    entries = []
    # 备份可被重命名为任意 .zip 名，故按全部 zip 列举（目录只存放备份文件）
    for f in sorted(backup_dir(data_dir).glob("*.zip"), reverse=True):
        st = f.stat()
        entries.append(
            {
                "name": f.name,
                "size": st.st_size,
                "created_at": datetime.fromtimestamp(st.st_mtime)
                .astimezone()
                .isoformat(timespec="seconds"),
            }
        )
    return entries


def resolve_backup(data_dir: Path, name: str) -> Path:
    """校验备份名（防路径穿越）并返回路径。不合法抛 ValueError，不存在抛 FileNotFoundError。"""
    if not BACKUP_NAME_RE.match(name):
        raise ValueError("非法的备份文件名")
    path = backup_dir(data_dir) / name
    if not path.is_file():
        raise FileNotFoundError("备份不存在")
    return path


def rename_backup(data_dir: Path, old_name: str, new_name: str) -> Path:
    """重命名备份文件。

    新名须匹配 BACKUP_NAME_RE（防路径穿越）；目标已存在抛 FileExistsError（拒绝覆盖），
    其余错误语义同 resolve_backup。返回新路径。
    """
    if not BACKUP_NAME_RE.match(new_name):
        raise ValueError("非法的备份文件名")
    src = resolve_backup(data_dir, old_name)
    dst = backup_dir(data_dir) / new_name
    if dst.exists():
        raise FileExistsError("目标备份已存在")
    dst = src.rename(dst)
    logger.info("Backup renamed: %s -> %s", old_name, new_name)
    return dst
