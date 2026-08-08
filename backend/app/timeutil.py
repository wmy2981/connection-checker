"""时间窗口判断，支持跨午夜；容器时区名称获取。"""
import os
from datetime import datetime

from app.models import TimeRange


def get_tz_name() -> str:
    """返回容器时区（TZ 环境变量）的 IANA 名称，供前端统一时间显示。

    常见部署设 TZ=Asia/Shanghai；未设置时按当前本地偏移兜底（Windows 上
    Python 不读 TZ 环境变量，此路径保证前后端显示一致）。
    """
    tz = os.environ.get("TZ", "").strip()
    if tz.startswith(":"):
        tz = tz[1:]
    if tz.startswith("/"):  # 绝对路径，如 /usr/share/zoneinfo/Asia/Shanghai
        parts = tz.strip("/").split("/")
        if "zoneinfo" in parts:
            tz = "/".join(parts[parts.index("zoneinfo") + 1:])
    if (
        tz
        and "/" in tz
        and not tz.startswith(("Etc/", "SystemV/", "posix/", "right/"))
    ):
        return tz
    # 未设 TZ 或非 IANA 名：按当前本地偏移返回固定偏移名（Etc/GMT 符号与偏移相反）
    offset = datetime.now().astimezone().utcoffset()
    if not offset or offset.total_seconds() == 0:
        return "UTC"
    total_min = int(offset.total_seconds() // 60)
    sign = "-" if total_min > 0 else "+"
    hh = abs(total_min) // 60
    mm = abs(total_min) % 60
    return f"Etc/GMT{sign}{hh if mm == 0 else f'{hh}:{mm:02d}'}"


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
