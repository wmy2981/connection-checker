"""应用设置：Webhook 告警配置（存于 config.json）。"""
from fastapi import APIRouter, Depends, Request

from app.auth import require_auth
from app.models import WebhookConfig
from app.storage import ConfigStore

router = APIRouter(prefix="/settings", tags=["settings"], dependencies=[Depends(require_auth)])


def _get_config_store(request: Request) -> ConfigStore:
    return request.app.state.config_store


@router.get("/webhook")
async def get_webhook(request: Request) -> WebhookConfig:
    return await _get_config_store(request).get_webhook_config()


@router.put("/webhook")
async def update_webhook(request: Request, payload: WebhookConfig) -> WebhookConfig:
    return await _get_config_store(request).update_webhook_config(payload)
