"""FastAPI 应用装配：生命周期管理、API 挂载、前端静态托管。"""
import logging
from contextlib import asynccontextmanager
from importlib.metadata import version as pkg_version
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api import api_router
from app.auth import Security
from app.config import Settings
from app.log_cleaner import LogCleaner
from app.logging_setup import configure
from app.notifier import Notifier
from app.s3_storage import S3Storage
from app.scheduler import Scheduler
from app.storage import ConfigStore, ResultStore, SecretsStore

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    cfg: Settings = app.state.settings
    cfg.ensure_dirs()
    config_store = ConfigStore(cfg.data_dir)
    app_cfg = await config_store.get_app_settings()
    # 日志装配必须在业务日志输出之前：控制台 + 每日文件，级别来自 config.json
    configure(cfg.data_dir / "logs", app_cfg.log_level)
    logger.info(
        "Application started: log level=%s, log dir=%s, data dir=%s",
        app_cfg.log_level,
        cfg.data_dir / "logs",
        cfg.data_dir,
    )
    secrets_store = SecretsStore(cfg.data_dir)
    s3_cfg = await config_store.get_s3_config()
    s3_store = None
    creds_ok = bool(secrets_store.s3_access_id and secrets_store.s3_access_key)
    if (
        app_cfg.storage_mode != "local"
        and s3_cfg.enabled
        and creds_ok
    ):
        s3_store = S3Storage(
            s3_cfg, secrets_store.s3_access_id, secrets_store.s3_access_key
        )
        logger.info(
            "Result storage mode=%s, S3 enabled at %s/%s",
            app_cfg.storage_mode,
            s3_cfg.endpoint,
            s3_cfg.bucket,
        )
    elif app_cfg.storage_mode != "local":
        # 配置要求 S3 但不可用：静默降级本地会让运维误以为数据在 S3
        logger.warning(
            "storage_mode=%s but S3 is not usable (enabled=%s credentials=%s); "
            "results will stay local only",
            app_cfg.storage_mode,
            s3_cfg.enabled,
            creds_ok,
        )
    result_store = ResultStore(
        cfg.data_dir / "results.jsonl",
        app_cfg.result_max_records,
        storage_mode=app_cfg.storage_mode,
        s3=s3_store,
    )
    security = Security(secrets_store, cfg)
    notifier = Notifier(config_store)
    scheduler = Scheduler(config_store, result_store, notifier, cfg, secrets_store)
    log_cleaner = LogCleaner(config_store, secrets_store, cfg)

    app.state.config_store = config_store
    app.state.result_store = result_store
    app.state.secrets_store = secrets_store
    app.state.security = security
    app.state.notifier = notifier
    app.state.scheduler = scheduler
    if not security.auth_enabled:
        logger.warning("CONNECTCHECKER_ACCESS_CODE not set, auth disabled (no-login mode)")
    else:
        logger.info("Auth enabled")

    await scheduler.start()
    await log_cleaner.start()
    try:
        yield
    finally:
        await scheduler.stop()
        await log_cleaner.stop()


def create_app(settings: Settings) -> FastAPI:
    app = FastAPI(
        title="connection-checker",
        version=pkg_version("connection-checker"),
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.include_router(api_router)
    _mount_frontend(app)
    return app


def _mount_frontend(app: FastAPI) -> None:
    """托管 Vue 构建产物：/assets 静态 + 其余路径回退到 index.html（SPA）。"""
    static_dir = Path(__file__).parent / "static"
    assets_dir = static_dir / "assets"
    if not assets_dir.exists():
        return
    app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa(full_path: str):
        if full_path:
            candidate = (static_dir / full_path).resolve()
            if candidate.is_relative_to(static_dir.resolve()) and candidate.is_file():
                return FileResponse(candidate)
        index = static_dir / "index.html"
        if index.exists():
            return FileResponse(index)
        return JSONResponse({"detail": "not found"}, status_code=404)


app = create_app(Settings())
