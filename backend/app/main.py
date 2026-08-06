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
from app.notifier import Notifier
from app.scheduler import Scheduler
from app.storage import ConfigStore, ResultStore, SecretsStore

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    cfg: Settings = app.state.settings
    cfg.ensure_dirs()
    config_store = ConfigStore(cfg.data_dir)
    result_store = ResultStore(cfg.data_dir / "results.jsonl", cfg.result_max_records)
    secrets_store = SecretsStore(cfg.data_dir)
    security = Security(secrets_store, cfg)
    notifier = Notifier(cfg.webhook_url, cfg.notify_fail_threshold)
    scheduler = Scheduler(config_store, result_store, notifier, cfg)

    app.state.config_store = config_store
    app.state.result_store = result_store
    app.state.secrets_store = secrets_store
    app.state.security = security
    app.state.scheduler = scheduler
    if security.generated_access_code:
        logger.warning(
            "未设置 CONNECTCHECKER_ACCESS_CODE，请使用自动生成的访问码登录: %s",
            security.generated_access_code,
        )

    await scheduler.start()
    try:
        yield
    finally:
        await scheduler.stop()


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
