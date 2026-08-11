"""应用元信息：容器时区、版本号等，供前端显示。非敏感信息，无需鉴权。"""
from importlib.metadata import version as pkg_version

from fastapi import APIRouter

from app.timeutil import get_tz_name

router = APIRouter(tags=["meta"])


@router.get("/meta")
async def meta() -> dict[str, str]:
    # 版本来自安装的包版本（pyproject.toml 的 project.version），Docker 中一致
    return {"tz": get_tz_name(), "version": pkg_version("connection-checker")}
