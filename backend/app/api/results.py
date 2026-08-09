"""检查结果查询与导出。"""
import csv
import io
import json
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response

from app.auth import require_auth
from app.models import Paginated, ResultFilter
from app.storage import ResultStore

router = APIRouter(prefix="/results", tags=["results"], dependencies=[Depends(require_auth)])


@router.get("")
async def query_results(
    request: Request,
    status: str | None = Query(default=None),
    ip: str | None = Query(default=None),
    target_name: str | None = Query(default=None),
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
        target_name=target_name,
        target_id=target_id,
        date=date,
        time_start=time_start,
        time_end=time_end,
        page=page,
        page_size=page_size,
    )
    return await store.query(filt)


def _export_filters(
    status: str | None = Query(default=None),
    ip: str | None = Query(default=None),
    target_name: str | None = Query(default=None),
    target_id: str | None = Query(default=None),
    date: str | None = Query(default=None),
    time_start: str | None = Query(default=None),
    time_end: str | None = Query(default=None),
) -> ResultFilter:
    return ResultFilter(
        status=status,
        ip=ip,
        target_name=target_name,
        target_id=target_id,
        date=date,
        time_start=time_start,
        time_end=time_end,
    )


def _stamp() -> str:
    """服务器本地时间戳（容器 TZ），用于导出文件名。"""
    return datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")


@router.get("/export.csv")
async def export_csv(
    request: Request, filt: Annotated[ResultFilter, Depends(_export_filters)]
) -> Response:
    store: ResultStore = request.app.state.result_store
    results = await store.export_all(filt)

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        ["时间", "目标名称", "IP/域名", "检查方式", "状态", "延迟(ms)", "消息", "附加数据"]
    )
    for r in results:
        local = r.checked_at.astimezone()
        writer.writerow(
            [
                local.strftime("%Y-%m-%d %H:%M:%S"),
                r.target_name or "",
                r.ip,
                r.check_method,
                r.status,
                r.latency_ms if r.latency_ms is not None else "",
                r.message,
                json.dumps(r.extra, ensure_ascii=False),
            ]
        )
    filename = f"results_{_stamp()}.csv"
    return Response(
        # utf-8-sig 写入 BOM，Excel/WPS 直接打开不乱码
        content=buf.getvalue().encode("utf-8-sig"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/export.json")
async def export_json(
    request: Request, filt: Annotated[ResultFilter, Depends(_export_filters)]
) -> Response:
    store: ResultStore = request.app.state.result_store
    results = await store.export_all(filt)
    data = [r.model_dump(mode="json") for r in results]
    filename = f"results_{_stamp()}.json"
    return Response(
        content=json.dumps(data, ensure_ascii=False).encode("utf-8"),
        media_type="application/json; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
