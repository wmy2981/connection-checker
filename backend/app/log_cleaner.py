"""日志自动清理：按 config.json 的 app.log_cleanup_mode 删除或上传 n 天前日志。

- none：不清理
- delete：直接删除超过 log_retention_days 天的本地日志文件
- upload：先上传到 S3（datapath/logs/ 下），成功后删除本地；失败保留本地并记录
  ERROR 日志，下次轮询重试。S3 对象永久保留，不自动清理。
"""
import asyncio
import logging
from datetime import datetime, timedelta
from pathlib import Path

from app.config import Settings
from app.s3_storage import S3Storage
from app.storage import ConfigStore, SecretsStore

logger = logging.getLogger(__name__)

CLEANUP_INTERVAL_SECONDS = 6 * 3600  # 每 6 小时轮询一次（幂等，早跑晚跑无副作用）


class LogCleaner:
    def __init__(
        self,
        config_store: ConfigStore,
        secrets_store: SecretsStore,
        settings: Settings,
    ) -> None:
        self.config_store = config_store
        self.secrets_store = secrets_store
        self.settings = settings
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        await self.run_once()
        self._task = asyncio.create_task(self._loop(), name="log-cleaner")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()

    async def _loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(CLEANUP_INTERVAL_SECONDS)
                await self.run_once()
        except asyncio.CancelledError:
            pass

    def _old_log_files(self, log_dir: Path, retention_days: int) -> list[Path]:
        cutoff = datetime.now().astimezone().date() - timedelta(days=retention_days)
        result = []
        for f in log_dir.glob("app-*.log"):
            try:
                stamp = datetime.strptime(f.name[len("app-") : -len(".log")], "%Y-%m-%d")
            except ValueError:
                continue
            if stamp.date() <= cutoff:
                result.append(f)
        return result

    async def run_once(self) -> None:
        app_cfg = await self.config_store.get_app_settings()
        mode = app_cfg.log_cleanup_mode
        if mode == "none":
            logger.debug("Log cleanup skipped (mode=none)")
            return
        log_dir = self.settings.data_dir / "logs"
        files = self._old_log_files(log_dir, app_cfg.log_retention_days)
        if not files:
            logger.debug(
                "Log cleanup: no files older than %d days",
                app_cfg.log_retention_days,
            )
            return

        if mode == "upload":
            await self._upload(files, app_cfg.log_retention_days)
        else:  # delete
            for f in files:
                try:
                    f.unlink(missing_ok=True)
                except OSError as e:
                    # 文件被占用（如导出流仍持有句柄）等删除失败：记录 ERROR 并继续，
                    # 不因单文件异常中断清理任务
                    logger.error(
                        "Failed to delete old log %s: %s; will retry next cycle",
                        f.name,
                        e,
                    )
                    continue
                logger.info(
                    "Deleted old log %s (retention %d days)",
                    f.name,
                    app_cfg.log_retention_days,
                )

    async def _upload(self, files: list[Path], retention_days: int) -> None:
        s3_cfg = await self.config_store.get_s3_config()
        secrets = self.secrets_store
        if not s3_cfg.enabled or not (secrets.s3_access_id and secrets.s3_access_key):
            logger.warning(
                "Log cleanup mode=upload but S3 not configured or credentials missing; skipped"
            )
            return
        storage = S3Storage(s3_cfg, secrets.s3_access_id, secrets.s3_access_key)
        prefix = f"{s3_cfg.datapath.rstrip('/')}/logs"
        for f in files:
            object_name = f"{prefix}/{f.name}"
            try:
                await asyncio.to_thread(storage.upload_file, object_name, f)
            except Exception as e:  # noqa: BLE001
                logger.error(
                    "Failed to upload log %s to s3://%s/%s: %s; kept locally for retry",
                    f.name,
                    s3_cfg.bucket,
                    object_name,
                    e,
                )
                continue
            f.unlink(missing_ok=True)
            logger.info(
                "Uploaded old log %s to s3://%s/%s and removed locally (retention %d days)",
                f.name,
                s3_cfg.bucket,
                object_name,
                retention_days,
            )
