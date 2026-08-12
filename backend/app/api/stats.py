"""概览统计。"""
from fastapi import APIRouter, Depends, Query, Request

from app.auth import require_auth
from app.models import StatsSummary

router = APIRouter(prefix="/stats", tags=["stats"], dependencies=[Depends(require_auth)])


@router.get("/summary")
async def summary(request: Request) -> StatsSummary:
    config_store = request.app.state.config_store
    result_store = request.app.state.result_store

    targets = await config_store.list_targets()
    latest = await result_store.latest_per_target([t.id for t in targets])
    uptime = await result_store.uptime_per_target([t.id for t in targets])
    notifier = request.app.state.notifier
    app_cfg = await config_store.get_app_settings()
    counts = await result_store.count_by_status(app_cfg.stats_window)
    recent = await result_store.recent(1)
    latest_check_at = recent[0].checked_at if recent else None

    target_status = []
    for t in targets:
        r = latest.get(t.id)
        up = uptime.get(t.id, {})
        target_status.append(
            {
                "target_id": t.id,
                "name": t.name,
                "ip": t.ip,
                "check_method": t.check_method,
                "enabled": t.enabled,
                "check_interval": t.check_interval,
                "last_status": r.status if r else None,
                "last_latency_ms": r.latency_ms if r else None,
                "last_checked_at": r.checked_at if r else None,
                "last_message": r.message if r else None,
                # 近 24 小时可用率（滚动窗口）；无样本时为 None
                "uptime_pct": up.get("uptime_pct"),
                "uptime_total": up.get("total"),
                # 当前连续失败次数（告警模块跟踪；成功/未失败过为 0）
                "consecutive_fails": notifier.consecutive_fails(t.id),
            }
        )

    return StatsSummary(
        total_targets=len(targets),
        enabled_targets=sum(1 for t in targets if t.enabled),
        last_total_checks=sum(counts.values()),
        last_success=counts["success"],
        last_fail=counts["fail"],
        last_timeout=counts["timeout"],
        last_error=counts["error"],
        stats_window=app_cfg.stats_window,
        latest_check_at=latest_check_at,
        target_status=target_status,
    )


@router.get("/trend")
async def trend(
    request: Request,
    hours: int = Query(default=24, ge=1, le=168),
    target_id: str | None = Query(default=None, description="按目标过滤，空为全部目标"),
    unit: str = Query(
        default="hour", pattern="^(hour|day)$", description="聚合粒度：hour 按小时 / day 按天"
    ),
) -> dict:
    result_store = request.app.state.result_store
    return {
        "hours": hours,
        "target_id": target_id,
        "unit": unit,
        "buckets": await result_store.trend(hours, target_id, unit),
    }
