"""应用设置：Webhook 告警配置、全局检查参数、S3 配置与 API Token。"""
import asyncio
import logging
import secrets

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.auth import require_auth
from app.icon_validate import validate_icon
from app.models import AppSettings, S3Config, WebhookConfig
from app.notifier import Notifier
from app.s3_storage import S3Storage
from app.storage import ConfigStore, SecretsStore

logger = logging.getLogger(__name__)

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
    saved = await _get_config_store(request).update_webhook_config(payload)
    logger.info(
        "Webhook config updated: enabled=%s url_set=%s fail_threshold=%d",
        saved.enabled,
        bool(saved.url),
        saved.fail_threshold,
    )
    return saved


@router.get("/app")
async def get_app_settings(request: Request) -> AppSettings:
    return await _get_config_store(request).get_app_settings()


@router.put("/app")
async def update_app_settings(request: Request, payload: AppSettings) -> AppSettings:
    store = _get_config_store(request)
    if payload.brand_icon:
        try:
            await asyncio.to_thread(validate_icon, payload.brand_icon)
        except ValueError as e:
            logger.error("Brand icon validation failed: %s", e)
            raise HTTPException(status_code=422, detail=f"品牌图标无效: {e}") from None
    # 依赖 S3 的选项要求 S3 已完整配置（含凭据），避免保存后静默退化为本地
    needs_s3 = payload.log_cleanup_mode == "upload" or payload.storage_mode in ("s3", "both")
    if needs_s3:
        s3_cfg = await store.get_s3_config()
        secrets: SecretsStore = request.app.state.secrets_store
        s3_ready = (
            s3_cfg.enabled
            and s3_cfg.endpoint
            and s3_cfg.bucket
            and s3_cfg.datapath
            and bool(secrets.s3_access_id and secrets.s3_access_key)
        )
        if not s3_ready:
            raise HTTPException(
                status_code=422,
                detail="该配置依赖 S3，请先在「S3 存储配置」中完成配置（含凭据）",
            )
    saved = await store.update_app_settings(payload)
    # 结果保留上限立即生效并裁剪超出部分
    request.app.state.result_store.resize(saved.result_max_records)
    logger.info(
        "App settings updated: storage_mode=%s log_level=%s cleanup_mode=%s "
        "result_max_records=%d stats_window=%d",
        saved.storage_mode,
        saved.log_level,
        saved.log_cleanup_mode,
        saved.result_max_records,
        saved.stats_window,
    )
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
    # 未提供的字段（exclude_unset）保留已保存配置：部分负载只改携带的字段
    saved = await store.get_s3_config()
    updates = payload.model_dump(exclude_unset=True, exclude={"access_id", "access_key"})
    cfg = S3Config.model_validate({**saved.model_dump(), **updates})
    if cfg.enabled and not (cfg.endpoint and cfg.bucket and cfg.datapath):
        raise HTTPException(status_code=422, detail="启用 S3 时 endpoint、bucket、数据路径必填")
    await store.update_s3_config(cfg)
    secrets.set_s3_credentials(payload.access_id, payload.access_key)
    return _s3_response(cfg, secrets)


@router.get("/api-token")
async def get_api_token(request: Request) -> dict:
    """返回 API 令牌明文（用户要求配置页回显展示，凭 require_auth 保护）。

    密钥类数据接口默认不回读明文，此接口是唯一例外。
    """
    secrets_store: SecretsStore = request.app.state.secrets_store
    token = secrets_store.api_token or None
    return {"has_token": bool(token), "token": token}


@router.post("/api-token/generate")
async def generate_api_token(request: Request) -> dict:
    """生成新 API Token：旧 token 立即失效。"""
    secrets_store: SecretsStore = request.app.state.secrets_store
    token = secrets_store.set_api_token(secrets.token_urlsafe(32))
    logger.info("API token generated, previous token invalidated")
    return {"token": token}


@router.delete("/api-token")
async def delete_api_token(request: Request) -> dict:
    """删除 API Token：外部 API 调用立即禁用。"""
    secrets_store: SecretsStore = request.app.state.secrets_store
    secrets_store.set_api_token(None)
    logger.info("API token deleted, external API access disabled")
    return {"ok": True}


@router.post("/s3/test")
async def test_s3_settings(
    request: Request, payload: S3ConfigPayload | None = None
) -> dict:
    """测试 S3 连接：可携带表单配置（凭据留空用已保存），否则用已保存配置。"""
    store = _get_config_store(request)
    secrets: SecretsStore = request.app.state.secrets_store
    if payload is None or not payload.model_fields_set:
        # 无 body 或空对象：用已保存配置
        cfg = await store.get_s3_config()
        access_id, access_key = secrets.s3_access_id, secrets.s3_access_key
    else:
        cfg = S3Config.model_validate(payload.model_dump(exclude={"access_id", "access_key"}))
        access_id = payload.access_id or secrets.s3_access_id
        access_key = payload.access_key or secrets.s3_access_key
    if not (cfg.endpoint and cfg.bucket):
        raise HTTPException(status_code=400, detail="请先填写 endpoint 与 bucket")
    if not (access_id and access_key):
        raise HTTPException(status_code=400, detail="请先填写 Access ID 与 Access Key")
    try:
        storage = S3Storage(cfg, access_id, access_key)
        exists = await asyncio.to_thread(storage.bucket_exists)
    except Exception as e:  # noqa: BLE001
        logger.error("S3 connection test failed: %s", e)
        raise HTTPException(status_code=502, detail=f"S3 连接失败: {e}") from None
    logger.info(
        "S3 connection test ok: endpoint=%s bucket=%s exists=%s",
        cfg.endpoint,
        cfg.bucket,
        exists,
    )
    if exists:
        return {"ok": True, "info": f"连接成功，bucket「{cfg.bucket}」存在"}
    return {"ok": True, "info": "连接成功，但 bucket 不存在（请在服务端创建）"}


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
