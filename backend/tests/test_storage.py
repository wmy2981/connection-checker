import asyncio
import json
from datetime import datetime, timedelta, timezone

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


async def test_config_load_errors_logged(tmp_path, caplog):
    """配置损坏时报 error 日志便于排查，原错误处理行为不变（回退默认/跳过）。"""
    import logging

    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True)

    # JSON 解析失败 → error + 重建默认配置
    (data_dir / "config.json").write_text("{broken json", encoding="utf-8")
    with caplog.at_level(logging.ERROR, logger="app.storage"):
        store = ConfigStore(data_dir)
    assert any("Failed to parse config.json" in r.message for r in caplog.records)
    assert await store.get_app_settings() == AppSettings()

    # 单条 target 损坏 → error + 跳过该条，其余正常
    valid_target = {
        "id": "ok1",
        "name": "正常",
        "ip": "8.8.8.8",
        "check_method": "ping",
        "check_interval": 60,
    }
    data = {
        "version": 1,
        "check_targets": [
            valid_target,
            {"id": "bad1", "ip": "", "check_method": "nonsense"},
            "not-a-dict",
        ],
        "webhook": {},
        "app": {},
    }
    (data_dir / "config.json").write_text(json.dumps(data), encoding="utf-8")
    caplog.clear()
    with caplog.at_level(logging.ERROR, logger="app.storage"):
        store = ConfigStore(data_dir)
    errors = [r for r in caplog.records if "Invalid check target" in r.message]
    assert len(errors) == 2  # bad1 与 not-a-dict 各一条
    assert (await store.get_target("ok1")) is not None
    assert (await store.get_target("bad1")) is None

    # app 节无效 → error + 默认值
    data["app"] = {"stats_window": "not-a-number"}
    (data_dir / "config.json").write_text(json.dumps(data), encoding="utf-8")
    caplog.clear()
    with caplog.at_level(logging.ERROR, logger="app.storage"):
        store = ConfigStore(data_dir)
    assert any("Invalid app settings" in r.message for r in caplog.records)
    assert await store.get_app_settings() == AppSettings()


class FakeS3:
    """内存版 S3 客户端：duck-typing S3Storage 接口，便于断言同步行为。"""

    def __init__(self, datapath: str = "data/"):
        from types import SimpleNamespace

        self.cfg = SimpleNamespace(datapath=datapath, bucket="cc")
        self.bucket = "cc"  # 对齐真实 S3Storage 接口（sync 成功日志访问该属性）
        self.objects: dict[str, bytes] = {}
        self.fail_put = False
        self.put_calls = 0

    def put_data(self, object_name: str, data: bytes) -> None:
        self.put_calls += 1
        if self.fail_put:
            raise RuntimeError("s3 down")
        self.objects[object_name] = data

    def get_data(self, object_name: str) -> bytes | None:
        return self.objects.get(object_name)

    def list_objects(self, prefix: str) -> list[str]:
        return sorted(k for k in self.objects if k.startswith(prefix))


class BrokenS3:
    cfg = FakeS3().cfg

    def list_objects(self, prefix: str):
        raise RuntimeError("s3 down")

    def get_data(self, object_name: str):
        raise RuntimeError("s3 down")


async def test_result_store_both_mode_syncs_to_s3(tmp_path):
    """both 模式：本地照常写，S3 按天对象同步，对象含记录内容。"""
    s3 = FakeS3()
    store = ResultStore(tmp_path / "results.jsonl", 100, storage_mode="both", s3=s3)
    r = _result("t1", "success", datetime.now(timezone.utc))
    await store.append(r)
    date = r.checked_at.astimezone().strftime("%Y-%m-%d")
    assert s3.put_calls == 1
    obj = s3.objects[f"data/results/{date}.jsonl"]
    assert r.model_dump_json().encode() in obj
    assert (tmp_path / "results.jsonl").exists()  # 本地文件仍写（兜底）


async def test_result_store_s3_sync_merges_existing(tmp_path):
    """S3 对象按 id 去重合并：新 append 不覆盖旧记录。"""
    s3 = FakeS3()
    store = ResultStore(tmp_path / "results.jsonl", 100, storage_mode="both", s3=s3)
    old = _result("t1", "success", datetime.now(timezone.utc))
    await store.append(old)
    date = old.checked_at.astimezone().strftime("%Y-%m-%d")
    new = _result("t2", "fail", datetime.now(timezone.utc))
    await store.append(new)
    obj = s3.objects[f"data/results/{date}.jsonl"].decode("utf-8")
    assert old.id in obj and new.id in obj


async def test_result_store_s3_sync_failure_keeps_local(tmp_path, caplog):
    """S3 写失败：ERROR 日志 + 不抛异常 + 记录留在本地文件。"""
    import logging

    s3 = FakeS3()
    store = ResultStore(tmp_path / "results.jsonl", 100, storage_mode="both", s3=s3)
    s3.fail_put = True
    with caplog.at_level(logging.ERROR, logger="app.storage"):
        await store.append(_result("t1", "success", datetime.now(timezone.utc)))
    assert any("S3 results sync failed" in r.message for r in caplog.records)
    assert (tmp_path / "results.jsonl").read_text(encoding="utf-8").strip()


async def test_result_store_s3_mode_loads_from_s3(tmp_path):
    """s3 模式启动时从 S3 加载全部对象。"""
    s3 = FakeS3()
    r = _result("t1", "success", datetime.now(timezone.utc))
    date = r.checked_at.astimezone().strftime("%Y-%m-%d")
    s3.objects[f"data/results/{date}.jsonl"] = (r.model_dump_json() + "\n").encode()
    store = ResultStore(tmp_path / "results.jsonl", 100, storage_mode="s3", s3=s3)
    recent = await store.recent(10)
    assert len(recent) == 1 and recent[0].id == r.id


async def test_result_store_s3_mode_merges_local_backfill(tmp_path):
    """s3 模式加载：S3 为主，本地文件补 S3 缺失的记录（失败期间不丢）。"""
    s3 = FakeS3()
    old = _result("t1", "success", datetime.now(timezone.utc))
    date = old.checked_at.astimezone().strftime("%Y-%m-%d")
    s3.objects[f"data/results/{date}.jsonl"] = (old.model_dump_json() + "\n").encode()
    fresh = _result("t2", "fail", datetime.now(timezone.utc))
    (tmp_path / "results.jsonl").write_text(fresh.model_dump_json() + "\n", encoding="utf-8")
    store = ResultStore(tmp_path / "results.jsonl", 100, storage_mode="s3", s3=s3)
    recent = await store.recent(10)
    assert {r.id for r in recent} == {old.id, fresh.id}


async def test_result_store_s3_load_failure_falls_back_local(tmp_path, caplog):
    """s3 模式 S3 不可达：WARN + 回退本地文件。"""
    import logging

    r = _result("t1", "success", datetime.now(timezone.utc))
    (tmp_path / "results.jsonl").write_text(r.model_dump_json() + "\n", encoding="utf-8")
    with caplog.at_level(logging.WARNING, logger="app.storage"):
        store = ResultStore(tmp_path / "results.jsonl", 100, storage_mode="s3", s3=BrokenS3())
    recent = await store.recent(10)
    assert len(recent) == 1
    assert any("falling back to local" in x.message for x in caplog.records)


def test_result_store_set_s3_mode_switches(tmp_path):
    """set_s3_mode 热更新：启用/禁用 S3 客户端与对象前缀。"""
    from app.models import S3Config

    store = ResultStore(tmp_path / "results.jsonl", 100)
    store.set_s3_mode(
        "both",
        S3Config(enabled=True, endpoint="http://x", bucket="b", datapath="data/"),
        "id",
        "key",
    )
    assert store._s3 is not None
    assert store._s3_prefix == "data/results/"
    store.set_s3_mode("local", None, "", "")
    assert store._s3 is None


async def test_result_store_backfills_history_on_startup(tmp_path):
    """启用 S3 启动时：本地全部历史日期（非当天）补传到 S3 对应对象。"""
    # 先以 local 模式写入两天数据
    local = ResultStore(tmp_path / "results.jsonl", 100, storage_mode="local")
    d1 = _result("t1", "success", datetime.now(timezone.utc) - timedelta(hours=25))
    d2 = _result("t2", "success", datetime.now(timezone.utc))
    await local.append(d1)
    await local.append(d2)
    date1 = d1.checked_at.astimezone().strftime("%Y-%m-%d")
    date2 = d2.checked_at.astimezone().strftime("%Y-%m-%d")
    assert date1 != date2

    s3 = FakeS3()
    store = ResultStore(tmp_path / "results.jsonl", 100, storage_mode="both", s3=s3)
    assert {f"data/results/{d}.jsonl" for d in (date1, date2)} <= set(s3.objects)
    assert not store._dirty_dates
    # 补传后本地记录仍在（合并去重，不丢）
    assert len(await store.recent(10)) == 2


async def test_set_s3_mode_backfills_history(tmp_path, monkeypatch):
    """热切换 local→both：本地历史数据由后台任务补传到 S3。"""
    from app.models import S3Config

    store = ResultStore(tmp_path / "results.jsonl", 100, storage_mode="local")
    d1 = _result("t1", "success", datetime.now(timezone.utc) - timedelta(hours=25))
    d2 = _result("t2", "success", datetime.now(timezone.utc))
    await store.append(d1)
    await store.append(d2)
    date1 = d1.checked_at.astimezone().strftime("%Y-%m-%d")
    date2 = d2.checked_at.astimezone().strftime("%Y-%m-%d")

    s3 = FakeS3()
    # set_s3_mode 内部构造真实 minio 客户端（会发网络请求），monkeypatch 换 FakeS3
    monkeypatch.setattr("app.storage.S3Storage", lambda _cfg, _id, _key: s3)
    store.set_s3_mode(
        "both",
        S3Config(enabled=True, endpoint="http://x", bucket="test-bucket", datapath="data/"),
        "id",
        "key",
    )
    # 等待后台补传任务完成
    for _ in range(200):
        if not store._dirty_dates:
            break
        await asyncio.sleep(0.01)
    assert not store._dirty_dates
    assert {f"data/results/{d}.jsonl" for d in (date1, date2)} <= set(s3.objects)


async def test_s3_sync_failure_retries_stale_date(tmp_path, caplog):
    """当天同步失败后日期保留；S3 恢复后，下次 append 把失败日期一并补传。"""
    import logging

    s3 = FakeS3()
    store = ResultStore(tmp_path / "results.jsonl", 100, storage_mode="both", s3=s3)
    old = _result("t1", "success", datetime.now(timezone.utc) - timedelta(hours=25))
    s3.fail_put = True
    with caplog.at_level(logging.ERROR, logger="app.storage"):
        await store.append(old)
    date_old = old.checked_at.astimezone().strftime("%Y-%m-%d")
    assert date_old in store._dirty_dates  # 失败日期保留待重试

    s3.fail_put = False
    caplog.clear()
    fresh = _result("t2", "fail", datetime.now(timezone.utc))
    await store.append(fresh)
    date_fresh = fresh.checked_at.astimezone().strftime("%Y-%m-%d")
    assert not store._dirty_dates
    expected = {f"data/results/{d}.jsonl" for d in (date_old, date_fresh)}
    assert set(s3.objects) == expected
