"""应用设置：Webhook 告警配置（存于 config.json）。"""
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.auth import require_auth
from app.models import WebhookConfig
from app.notifier import Notifier
from app.storage import ConfigStore

router = APIRouter(prefix="/settings", tags=["settings"], dependencies=[Depends(require_auth)])


def _get_config_store(request: Request) -> ConfigStore:
    return request.app.state.config_store


class WebhookTestRequest(BaseModel):
    """测试推送可携带目标地址；不传则用已保存的配置。"""

    url: str | None = Field(default=None, max_length=500)


@router.get("/webhook")
async def get_webhook(request: Request) -> WebhookConfig:
    return await _get_config_store(request).get_webhook_config()


@router.put("/webhook")
async def update_webhook(request: Request, payload: WebhookConfig) -> WebhookConfig:
    return await _get_config_store(request).update_webhook_config(payload)


@router.post("/webhook/test")
async def test_webhook(
    request: Request, payload: WebhookTestRequest | None = None
) -> dict:
    """向 Webhook 地址推送一条测试消息，验证配置可用。"""
    store = _get_config_store(request)
    cfg = await store.get_webhook_config()
    url = (payload.url if payload and payload.url else cfg.url) or None
    if not url:
        raise HTTPException(status_code=400, detail="请先填写 Webhook 地址")
    notifier: Notifier = request.app.state.notifier
    ok, info = await notifier.send_test(url)
    if not ok:
        raise HTTPException(status_code=502, detail=f"推送失败: {info}")
    return {"ok": True, "info": info}
