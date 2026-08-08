"""应用元信息：容器时区等，供前端统一时间显示。时区名非敏感信息，无需鉴权。"""
from fastapi import APIRouter

from app.timeutil import get_tz_name

router = APIRouter(tags=["meta"])


@router.get("/meta")
async def meta() -> dict[str, str]:
    return {"tz": get_tz_name()}
