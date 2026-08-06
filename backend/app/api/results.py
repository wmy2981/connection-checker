"""检查结果查询。"""
from fastapi import APIRouter, Depends, Query, Request

from app.auth import require_auth
from app.models import Paginated, ResultFilter
from app.storage import ResultStore

router = APIRouter(prefix="/results", tags=["results"], dependencies=[Depends(require_auth)])


@router.get("")
async def query_results(
    request: Request,
    status: str | None = Query(default=None),
    ip: str | None = Query(default=None),
    target_id: str | None = Query(default=None),
    date: str | None = Query(default=None),
    time_start: str | None = Query(default=None),
    time_end: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
) -> Paginated:
    store: ResultStore = request.app.state.result_store
    filt = ResultFilter(
        status=status,
        ip=ip,
        target_id=target_id,
        date=date,
        time_start=time_start,
        time_end=time_end,
        page=page,
        page_size=page_size,
    )
    return await store.query(filt)
