from datetime import datetime

from app.models import TimeRange
from app.timeutil import get_tz_name, hhmm_in_range, is_time_in_ranges

NIGHT = [TimeRange(start="22:00", end="06:00")]
DAY = [TimeRange(start="00:00", end="23:59")]
WORK_HOURS = [TimeRange(start="09:00", end="18:00")]


def _dt(hhmm: str) -> datetime:
    h, m = hhmm.split(":")
    return datetime(2026, 8, 6, int(h), int(m))


def test_within_range():
    assert is_time_in_ranges(_dt("10:30"), WORK_HOURS)


def test_outside_range():
    assert not is_time_in_ranges(_dt("08:59"), WORK_HOURS)
    assert not is_time_in_ranges(_dt("18:01"), WORK_HOURS)


def test_empty_ranges_always_true():
    assert is_time_in_ranges(_dt("12:00"), [])
    assert is_time_in_ranges(_dt("12:00"), None)  # type: ignore[arg-type]


def test_all_day_range():
    assert is_time_in_ranges(_dt("00:00"), DAY)
    assert is_time_in_ranges(_dt("23:59"), DAY)


def test_cross_midnight():
    assert is_time_in_ranges(_dt("23:30"), NIGHT)
    assert is_time_in_ranges(_dt("05:30"), NIGHT)
    assert not is_time_in_ranges(_dt("12:00"), NIGHT)
    assert is_time_in_ranges(_dt("22:00"), NIGHT)
    assert is_time_in_ranges(_dt("06:00"), NIGHT)


def test_boundary_inclusive():
    assert is_time_in_ranges(_dt("09:00"), WORK_HOURS)
    assert is_time_in_ranges(_dt("18:00"), WORK_HOURS)


def test_hhmm_string_variant():
    assert hhmm_in_range("23:00", NIGHT)
    assert not hhmm_in_range("12:00", NIGHT)
    assert hhmm_in_range("10:00", WORK_HOURS)


def test_get_tz_name_iana(monkeypatch):
    monkeypatch.setenv("TZ", "Asia/Shanghai")
    assert get_tz_name() == "Asia/Shanghai"


def test_get_tz_name_abs_path(monkeypatch):
    monkeypatch.setenv("TZ", "/usr/share/zoneinfo/America/New_York")
    assert get_tz_name() == "America/New_York"


def test_get_tz_name_colon_prefix(monkeypatch):
    monkeypatch.setenv("TZ", ":Asia/Tokyo")
    assert get_tz_name() == "Asia/Tokyo"


def test_get_tz_name_without_tz_falls_back_to_offset(monkeypatch):
    monkeypatch.delenv("TZ", raising=False)
    name = get_tz_name()
    # 无 TZ 时按本地偏移返回固定偏移名或 UTC
    assert name == "UTC" or name.startswith("Etc/GMT")
