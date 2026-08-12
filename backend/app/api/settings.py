"""应用设置：Webhook 告警配置、全局检查参数与 S3 配置（均存于 config.json）。"""
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.auth import require_auth
from app.models import AppSettings, S3Config, WebhookConfig
from app.notifier import Notifier
from app.storage import ConfigStore, SecretsStore

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


@router.get("/app")
async def get_app_settings(request: Request) -> AppSettings:
    return await _get_config_store(request).get_app_settings()


@router.put("/app")
async def update_app_settings(request: Request, payload: AppSettings) -> AppSettings:
    store = _get_config_store(request)
    saved = await store.update_app_settings(payload)
    # 结果保留上限立即生效并裁剪超出部分
    request.app.state.result_store.resize(saved.result_max_records)
    return saved


class S3ConfigPayload(S3Config):
    """PUT /settings/s3 请求体：凭据字段留空/为 null 表示不修改。"""

    access_id: str | None = Field(default=None, max_length=255)
    access_key: str | None = Field(default=None, max_length=255)


class S3ConfigResponse(BaseModel):
    """S3 配置响应：不含密钥明文，只暴露凭据是否已配置。"""

    enabled: bool
    endpoint: str
    bucket: str
    region: str | None
    datapath: str
    has_credentials: bool


def _s3_response(cfg: S3Config, secrets: SecretsStore) -> S3ConfigResponse:
    return S3ConfigResponse(
        enabled=cfg.enabled,
        endpoint=cfg.endpoint,
        bucket=cfg.bucket,
        region=cfg.region,
        datapath=cfg.datapath,
        has_credentials=bool(secrets.s3_access_id and secrets.s3_access_key),
    )


@router.get("/s3")
async def get_s3_settings(request: Request) -> S3ConfigResponse:
    cfg = await _get_config_store(request).get_s3_config()
    secrets: SecretsStore = request.app.state.secrets_store
    return _s3_response(cfg, secrets)


@router.put("/s3")
async def update_s3_settings(
    request: Request, payload: S3ConfigPayload
) -> S3ConfigResponse:
    store = _get_config_store(request)
    secrets: SecretsStore = request.app.state.secrets_store
    cfg = S3Config.model_validate(payload.model_dump(exclude={"access_id", "access_key"}))
    if cfg.enabled and not (cfg.endpoint and cfg.bucket and cfg.datapath):
        raise HTTPException(status_code=422, detail="启用 S3 时 endpoint、bucket、数据路径必填")
    await store.update_s3_config(cfg)
    secrets.set_s3_credentials(payload.access_id, payload.access_key)
    return _s3_response(cfg, secrets)


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
