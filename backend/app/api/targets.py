"""检查目标 CRUD。"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request

from app.auth import require_auth
from app.models import Target, TargetCreate, TargetUpdate
from app.scheduler import Scheduler
from app.storage import ConfigStore

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
    return target


@router.put("/{target_id}")
async def update_target(request: Request, target_id: str, payload: TargetUpdate) -> Target:
    store = _get_config_store(request)
    existing = await store.get_target(target_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="目标不存在")
    merged = existing.model_copy(update=payload.model_dump(exclude_unset=True))
    merged.updated_at = datetime.now(timezone.utc)
    await store.upsert_target(merged)
    await _get_scheduler(request).reconcile()
    return merged


@router.delete("/{target_id}", status_code=204)
async def delete_target(request: Request, target_id: str) -> None:
    store = _get_config_store(request)
    if not await store.delete_target(target_id):
        raise HTTPException(status_code=404, detail="目标不存在")
    await _get_scheduler(request).reconcile()
