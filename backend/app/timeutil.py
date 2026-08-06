"""时间窗口判断，支持跨午夜。"""
from datetime import datetime

from app.models import TimeRange


def _to_minutes(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def is_time_in_ranges(now: datetime, ranges: list[TimeRange]) -> bool:
    """now 是否落在任一范围内。start > end 视为跨午夜（22:00-06:00）。"""
    if not ranges:
        return True
    minutes = now.hour * 60 + now.minute
    for r in ranges:
        start = _to_minutes(r.start)
        end = _to_minutes(r.end)
        if start <= end:
            if start <= minutes <= end:
                return True
        else:
            if minutes >= start or minutes <= end:
                return True
    return False


def hhmm_in_range(hhmm: str, ranges: list[TimeRange]) -> bool:
    """HH:MM 字符串版本，用于结果筛选的时间段过滤。"""
    if not ranges:
        return True
    minutes = _to_minutes(hhmm)
    for r in ranges:
        start = _to_minutes(r.start)
        end = _to_minutes(r.end)
        if start <= end:
            if start <= minutes <= end:
                return True
        else:
            if minutes >= start or minutes <= end:
                return True
    return False
