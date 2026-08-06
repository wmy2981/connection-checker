"""手动立即检查。"""
from fastapi import APIRouter, Depends, HTTPException, Request

from app.auth import require_auth
from app.models import CheckResult, RunRequest
from app.scheduler import Scheduler

router = APIRouter(prefix="/checks", tags=["checks"], dependencies=[Depends(require_auth)])


@router.post("/run")
async def run_checks(request: Request, body: RunRequest | None = None) -> list[CheckResult]:
    scheduler: Scheduler = request.app.state.scheduler
    target_id = body.target_id if body else None
    if target_id is not None:
        store = request.app.state.config_store
        target = await store.get_target(target_id)
        if target is None:
            raise HTTPException(status_code=404, detail="目标不存在")
    return await scheduler.manual_run(target_id)
