import json
from datetime import datetime, timezone

from app.models import AppSettings, CheckResult, ResultFilter, Target, TimeRange, WebhookConfig
from app.storage import ConfigStore, ResultStore


def _target(tid: str, ip: str = "8.8.8.8") -> Target:
    return Target(
        id=tid,
        name=f"目标{tid}",
        ip=ip,
        check_method="ping",
        check_interval=60,
        time_ranges=[TimeRange(start="00:00", end="23:59")],
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )


def _result(tid: str, status: str, checked_at: datetime) -> CheckResult:
    return CheckResult(
        target_id=tid,
        target_name=f"目标{tid}",
        ip="8.8.8.8",
        check_method="ping",
        status=status,
        message="ok",
        checked_at=checked_at,
    )


async def test_config_store_crud(tmp_path):
    store = ConfigStore(tmp_path / "data")
    t = _target("a1")
    await store.upsert_target(t)
    assert (await store.get_target("a1")) == t
    assert len(await store.list_targets()) == 1
    assert store.file_mtime() is not None

    await store.delete_target("a1")
    assert await store.get_target("a1") is None
    assert await store.delete_target("a1") is False


async def test_config_store_persists_and_reloads(tmp_path):
    store = ConfigStore(tmp_path / "data")
    await store.upsert_target(_target("b1"))
    # 从磁盘重建
    store2 = ConfigStore(tmp_path / "data")
    assert await store2.get_target("b1") is not None
    raw = json.loads((tmp_path / "data" / "config.json").read_text(encoding="utf-8"))
    assert raw["version"] == 1
    assert len(raw["check_targets"]) == 1


async def test_result_store_append_query(tmp_path):
    store = ResultStore(tmp_path / "results.jsonl", max_records=100)
    for _ in range(5):
        await store.append(_result("t1", "success", datetime.now(timezone.utc)))
    await store.append(_result("t2", "fail", datetime.now(timezone.utc)))

    all_res = await store.query(ResultFilter(page_size=100))
    assert all_res.total == 6
    # 最新在前
    assert all_res.results[0].target_id == "t2"

    fails = await store.query(ResultFilter(status="fail", page_size=100))
    assert fails.total == 1

    ip_match = await store.query(ResultFilter(ip="8.8.8.8", page_size=100))
    assert ip_match.total == 6

    t1 = await store.query(ResultFilter(target_id="t1", page_size=100))
    assert t1.total == 5


async def test_result_store_trims_max(tmp_path):
    store = ResultStore(tmp_path / "results.jsonl", max_records=3)
    for _ in range(5):
        await store.append(_result("t1", "success", datetime.now(timezone.utc)))
    recent = await store.recent(100)
    assert len(recent) == 3
    # 文件也应被截断为 3 行
    lines = [
        line
        for line in (tmp_path / "results.jsonl").read_text(encoding="utf-8").splitlines()
        if line
    ]
    assert len(lines) == 3


async def test_result_store_loads_history(tmp_path):
    store = ResultStore(tmp_path / "results.jsonl", max_records=10)
    await store.append(_result("t1", "success", datetime.now(timezone.utc)))
    await store.append(_result("t1", "fail", datetime.now(timezone.utc)))

    store2 = ResultStore(tmp_path / "results.jsonl", max_records=10)
    assert (await store2.recent(10))[0].status == "fail"


async def test_result_store_ip_wildcard(tmp_path):
    store = ResultStore(tmp_path / "results.jsonl", max_records=100)
    ips = ["192.168.1.5", "192.168.2.9", "10.0.0.1", "192.168.1.200"]
    for i, ip in enumerate(ips):
        await store.append(
            CheckResult(
                target_id=f"t{i}",
                target_name=f"目标{i}",
                ip=ip,
                check_method="ping",
                status="success",
                checked_at=datetime.now(timezone.utc),
            )
        )

    assert (await store.query(ResultFilter(ip="192.168.*", page_size=100))).total == 3
    assert (await store.query(ResultFilter(ip="192.168.1.*", page_size=100))).total == 2
    # 无通配符时保持原有子串匹配
    assert (await store.query(ResultFilter(ip="168.1", page_size=100))).total == 2


async def test_result_store_filter_by_target_name(tmp_path):
    store = ResultStore(tmp_path / "results.jsonl", max_records=100)
    for _ in range(3):
        await store.append(_result("a", "success", datetime.now(timezone.utc)))
    await store.append(
        CheckResult(
            target_id="b",
            target_name="内网",
            ip="10.0.0.2",
            check_method="ping",
            status="success",
            checked_at=datetime.now(timezone.utc),
        )
    )

    assert (await store.query(ResultFilter(target_name="目标a", page_size=100))).total == 3
    assert (await store.query(ResultFilter(target_name="内网", page_size=100))).total == 1
    assert (await store.query(ResultFilter(target_name="不存在", page_size=100))).total == 0


async def test_config_backfills_missing_notify_enabled(tmp_path):
    """旧版 config.json 无 notify_enabled 时，加载后自动补 true 并写回磁盘。"""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    old = {
        "version": 1,
        "last_updated": "2026-08-09T00:00:00+08:00",
        "check_targets": [
            {
                "id": "old1",
                "name": "旧目标",
                "ip": "8.8.8.8",
                "check_method": "ping",
                "check_interval": 60,
                "time_ranges": [{"start": "00:00", "end": "23:59"}],
                "enabled": True,
                "created_at": "2026-08-01T00:00:00Z",
                "updated_at": "2026-08-01T00:00:00Z",
            }
        ],
        "webhook": {},
    }
    (data_dir / "config.json").write_text(
        json.dumps(old, ensure_ascii=False), encoding="utf-8"
    )

    store = ConfigStore(data_dir)
    assert (await store.get_target("old1")).notify_enabled is True
    raw = json.loads((data_dir / "config.json").read_text(encoding="utf-8"))
    assert raw["check_targets"][0]["notify_enabled"] is True

    # 已含字段的新配置不会被重复写（无多余改动），再次加载也保持
    store2 = ConfigStore(data_dir)
    assert (await store2.get_target("old1")).notify_enabled is True


async def test_config_store_app_settings_persists_and_reloads(tmp_path):
    store = ConfigStore(tmp_path / "data")
    assert await store.get_app_settings() == AppSettings()

    await store.update_app_settings(
        AppSettings(
            result_max_records=12345,
            ping_count=6,
            connect_timeout=1.5,
            http_timeout=2.5,
        )
    )

    store2 = ConfigStore(tmp_path / "data")
    cfg = await store2.get_app_settings()
    assert cfg.result_max_records == 12345
    assert cfg.ping_count == 6
    assert cfg.connect_timeout == 1.5
    assert cfg.http_timeout == 2.5

    raw = json.loads((tmp_path / "data" / "config.json").read_text(encoding="utf-8"))
    assert raw["app"]["http_timeout"] == 2.5


async def test_result_store_resize_trims(tmp_path):
    store = ResultStore(tmp_path / "results.jsonl", max_records=100)
    for _ in range(5):
        await store.append(_result("t1", "success", datetime.now(timezone.utc)))

    store.resize(3)
    assert len(await store.recent(100)) == 3
    lines = [
        line
        for line in (tmp_path / "results.jsonl").read_text(encoding="utf-8").splitlines()
        if line
    ]
    assert len(lines) == 3

    # 相同上限为幂等操作
    store.resize(3)
    assert len(await store.recent(100)) == 3


async def test_config_store_webhook_persists_and_reloads(tmp_path):
    store = ConfigStore(tmp_path / "data")
    assert await store.get_webhook_config() == WebhookConfig()

    await store.update_webhook_config(
        WebhookConfig(enabled=True, url="https://gotify.example.com/message", fail_threshold=5)
    )

    store2 = ConfigStore(tmp_path / "data")
    cfg = await store2.get_webhook_config()
    assert cfg.url == "https://gotify.example.com/message"
    assert cfg.fail_threshold == 5
    assert cfg.enabled is True

    raw = json.loads((tmp_path / "data" / "config.json").read_text(encoding="utf-8"))
    assert raw["webhook"]["fail_threshold"] == 5


async def test_result_store_trend(tmp_path):
    store = ResultStore(tmp_path / "results.jsonl", max_records=100)
    now = datetime.now(timezone.utc)
    for _ in range(3):
        await store.append(
            CheckResult(
                target_id="t1",
                target_name="目标t1",
                ip="8.8.8.8",
                check_method="ping",
                status="success",
                latency_ms=10.0,
                checked_at=now,
            )
        )
    await store.append(_result("t1", "fail", now))

    buckets = await store.trend(hours=24)
    assert len(buckets) == 24
    last = buckets[-1]  # 当前小时桶
    assert last["total"] == 4
    assert last["success"] == 3
    assert last["fail"] == 1
    assert last["timeout"] == 0
    assert last["error"] == 0
    assert last["avg_latency_ms"] == 10.0


async def test_latest_per_target_and_counts(tmp_path):
    store = ResultStore(tmp_path / "results.jsonl", max_records=100)
    for _ in range(3):
        await store.append(_result("t1", "success", datetime.now(timezone.utc)))
    await store.append(_result("t1", "fail", datetime.now(timezone.utc)))
    await store.append(_result("t2", "timeout", datetime.now(timezone.utc)))

    latest = await store.latest_per_target(["t1", "t2"])
    assert latest["t1"].status == "fail"
    assert latest["t2"].status == "timeout"

    counts = await store.count_by_status()
    assert counts["success"] == 3
    assert counts["fail"] == 1
    assert counts["timeout"] == 1


async def test_result_store_datetime_range_cross_day(tmp_path):
    """start_at/end_at 完整时间范围过滤，支持跨日（如 22:00 到次日 06:00）。"""
    store = ResultStore(tmp_path / "results.jsonl", max_records=100)
    # 本地时区下的跨日窗口：08-09 22:00 -> 08-10 06:00
    night = datetime(2026, 8, 9, 22, 0).astimezone()
    early = datetime(2026, 8, 10, 5, 30).astimezone()
    outside = datetime(2026, 8, 10, 8, 0).astimezone()
    await store.append(_result("t1", "success", night))
    await store.append(_result("t1", "success", early))
    await store.append(_result("t1", "success", outside))

    hits = await store.query(
        ResultFilter(start_at="2026-08-09T22:00:00", end_at="2026-08-10T06:00:00", page_size=100)
    )
    assert hits.total == 2  # 22:00 与次日 05:30 在窗口内，08:00 排除

    # 只给起始（无结束）：窗口内 + 之后的全部
    hits = await store.query(ResultFilter(start_at="2026-08-10T00:00:00", page_size=100))
    assert hits.total == 2

    # 只给结束（无起始）
    hits = await store.query(ResultFilter(end_at="2026-08-10T06:00:00", page_size=100))
    assert hits.total == 2
