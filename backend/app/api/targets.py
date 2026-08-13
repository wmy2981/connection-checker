"""检查目标 CRUD。"""
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request

from app.auth import require_auth
from app.models import Target, TargetCreate, TargetUpdate
from app.scheduler import Scheduler
from app.storage import ConfigStore

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/targets", tags=["targets"], dependencies=[Depends(require_auth)])


def _get_config_store(request: Request) -> ConfigStore:
    return request.app.state.config_store


def _get_scheduler(request: Request) -> Scheduler:
    return request.app.state.scheduler


@router.get("")
async def list_targets(request: Request) -> list[Target]:
    return await _get_config_store(request).list_targets()


@router.post("", status_code=201)
async def create_target(request: Request, payload: TargetCreate) -> Target:
    store = _get_config_store(request)
    now = datetime.now(timezone.utc)
    target = Target(
        id=ConfigStore.new_target_id(store.targets),
        **payload.model_dump(),
        created_at=now,
        updated_at=now,
    )
    await store.upsert_target(target)
    await _get_scheduler(request).reconcile()
    logger.info(
        "Target created %s (%s) [%s] interval=%ss",
        target.name or target.ip,
        target.id,
        target.check_method,
        target.check_interval,
    )
    return target


@router.put("/{target_id}")
async def update_target(request: Request, target_id: str, payload: TargetUpdate) -> Target:
    store = _get_config_store(request)
    existing = await store.get_target(target_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="目标不存在")
    # 不用 model_copy(update=dict)：它不重新验证嵌套模型，会把 time_ranges 变成
    # dict 导致调度循环抛 AttributeError 而静默杀死定时任务。改为整体重新验证。
    data = {**existing.model_dump(), **payload.model_dump(exclude_unset=True)}
    data["updated_at"] = datetime.now(timezone.utc)
    merged = Target.model_validate(data)
    await store.upsert_target(merged)
    await _get_scheduler(request).reconcile()
    logger.info(
        "Target updated %s (%s) fields=%s",
        merged.name or merged.ip,
        merged.id,
        sorted(payload.model_fields_set),
    )
    return merged


@router.delete("/{target_id}", status_code=204)
async def delete_target(request: Request, target_id: str) -> None:
    store = _get_config_store(request)
    if not await store.delete_target(target_id):
        raise HTTPException(status_code=404, detail="目标不存在")
    await _get_scheduler(request).reconcile()
    logger.info("Target deleted %s", target_id)
