"""应用元信息：容器时区、版本号等，供前端显示。非敏感信息，无需鉴权。"""
import re
from importlib.metadata import version as pkg_version
from pathlib import Path

from fastapi import APIRouter

from app.timeutil import get_tz_name

router = APIRouter(tags=["meta"])


def _app_version() -> str:
    """优先读 pyproject.toml 的原始版本号（保持 x.y.z.beta.n 形式）。

    包安装版本会被 setuptools 归一化（1.8.0.beta.1 → 1.8.0b1），显示不友好；
    项目根（本地仓库或 Docker /app）的 pyproject.toml 均存在，读取失败时兜底用包版本。
    """
    for candidate in (
        Path(__file__).resolve().parents[3] / "pyproject.toml",
        Path("pyproject.toml").resolve(),
    ):
        try:
            text = candidate.read_text(encoding="utf-8")
        except OSError:
            continue
        m = re.search(r'^version\s*=\s*"([^"]+)"', text, re.M)
        if m:
            return m.group(1)
    return pkg_version("connection-checker")


@router.get("/meta")
async def meta() -> dict[str, str]:
    return {"tz": get_tz_name(), "version": _app_version()}
