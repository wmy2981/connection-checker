import json
import re

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.models import AppSettings, Target
from app.notifier import Notifier
from app.scheduler import Scheduler
from app.storage import ConfigStore, ResultStore


def _payload(name: str = "测试", method: str = "ping", ip: str = "8.8.8.8") -> dict:
    return {"name": name, "ip": ip, "check_method": method, "check_interval": 60}


def test_no_access_code_disables_auth(tmp_path):
    """未设置访问码 = 免认证模式：直接访问面板，登录接口随意通过。"""
    settings = Settings(
        _env_file=None,
        data_dir=tmp_path / "data",
        access_code="",
        jwt_secret="x" * 40,
    )
    app = create_app(settings)
    with TestClient(app) as client:
        assert client.get("/api/v1/auth/me").json()["authenticated"] is True
        assert client.get("/api/v1/targets").status_code == 200
        resp = client.post("/api/v1/auth/login", json={"access_code": "anything"})
        assert resp.status_code == 200


def test_login_wrong_code(client: TestClient):
    resp = client.post("/api/v1/auth/login", json={"access_code": "nope"})
    assert resp.status_code == 401


def test_me_unauthenticated(client: TestClient):
    assert client.get("/api/v1/auth/me").json()["authenticated"] is False


def test_meta_public(client: TestClient):
    """meta 端点无需登录，返回容器时区名称与原始版本号。"""
    resp = client.get("/api/v1/meta")
    assert resp.status_code == 200
    tz = resp.json()["tz"]
    assert tz and "/" in tz or tz in ("UTC",)
    # 版本号保持 pyproject 原始形式（x.y.z / x.y.z.alpha.n / x.y.z.beta.n），非 PEP 440 归一化
    version = resp.json()["version"]
    assert re.fullmatch(r"\d+\.\d+\.\d+(?:\.(?:alpha|beta)\.\d+)?", version)


def test_login_ok_and_me(client: TestClient):
    resp = client.post("/api/v1/auth/login", json={"access_code": "test-access-code"})
    assert resp.status_code == 200
    assert client.get("/api/v1/auth/me").json()["authenticated"] is True


def test_requires_auth(client: TestClient):
    assert client.get("/api/v1/targets").status_code == 401
    assert client.get("/api/v1/results").status_code == 401
    assert client.get("/api/v1/stats/summary").status_code == 401


def test_crud_flow(logged_client: TestClient):
    created = logged_client.post("/api/v1/targets", json=_payload())
    assert created.status_code == 201
    target = created.json()
    tid = target["id"]
    assert target["check_interval"] == 60

    listed = logged_client.get("/api/v1/targets").json()
    assert len(listed) == 1

    updated = logged_client.put(
        f"/api/v1/targets/{tid}", json={"name": "改名", "check_interval": 120}
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "改名"
    assert updated.json()["check_interval"] == 120
    # 未提供的字段保持不变
    assert updated.json()["ip"] == "8.8.8.8"

    assert logged_client.delete(f"/api/v1/targets/{tid}").status_code == 204
    assert logged_client.get("/api/v1/targets").json() == []
    assert logged_client.delete(f"/api/v1/targets/{tid}").status_code == 404


def test_create_target_validation(logged_client: TestClient):
    resp = logged_client.post("/api/v1/targets", json={"ip": "", "check_method": "ping"})
    assert resp.status_code == 422
    resp = logged_client.post(
        "/api/v1/targets", json={"ip": "1.1.1.1", "check_method": "nonsense"}
    )
    assert resp.status_code == 422


def test_csrf_content_type_check(logged_client: TestClient):
    body = '{"ip":"1.1.1.1","check_method":"ping"}'
    resp = logged_client.post(
        "/api/v1/targets", content=body, headers={"content-type": "text/plain"}
    )
    assert resp.status_code == 415


def test_manual_run_and_results(logged_client: TestClient, fake_checker, no_scheduler):
    fake_checker(status="success", message="假检查成功", latency_ms=12.3)
    logged_client.post("/api/v1/targets", json=_payload())

    resp = logged_client.post("/api/v1/checks/run", json={})
    assert resp.status_code == 200
    results = resp.json()
    assert len(results) == 1
    assert results[0]["status"] == "success"

    queried = logged_client.get("/api/v1/results").json()
    assert queried["total"] == 1
    assert queried["results"][0]["latency_ms"] == 12.3

    ok = logged_client.get("/api/v1/results", params={"status": "success"}).json()
    assert ok["total"] == 1
    none = logged_client.get("/api/v1/results", params={"status": "timeout"}).json()
    assert none["total"] == 0


def test_results_export_csv(logged_client: TestClient, fake_checker, no_scheduler):
    fake_checker(status="success", message="假检查成功", latency_ms=12.3)
    logged_client.post("/api/v1/targets", json=_payload())
    logged_client.post("/api/v1/checks/run", json={})

    resp = logged_client.get("/api/v1/results/export.csv")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    lines = resp.content.decode("utf-8-sig").splitlines()
    assert lines[0].startswith("时间")
    assert len(lines) == 2  # 表头 + 1 行
    assert "success" in lines[1]
    assert "12.3" in lines[1]

    # 筛选条件同样作用于导出
    filtered = logged_client.get(
        "/api/v1/results/export.csv", params={"status": "timeout"}
    )
    assert len(filtered.content.decode("utf-8-sig").splitlines()) == 1  # 仅表头


def test_results_export_json(logged_client: TestClient, fake_checker, no_scheduler):
    fake_checker(status="success", message="假检查成功", latency_ms=12.3)
    logged_client.post("/api/v1/targets", json=_payload())
    logged_client.post("/api/v1/checks/run", json={})

    resp = logged_client.get("/api/v1/results/export.json")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/json")
    data = resp.json()
    assert isinstance(data, list) and len(data) == 1
    assert data[0]["status"] == "success"
    assert data[0]["latency_ms"] == 12.3


def test_manual_run_concurrent_targets(logged_client: TestClient, fake_checker, no_scheduler):
    """多个目标手动全部检查：并发执行且全部返回（回归：串行会逐个等待超时）。"""
    fake_checker(status="success", message="ok", latency_ms=1.0)
    for i in range(5):
        logged_client.post("/api/v1/targets", json=_payload(name=f"c-{i}", ip=f"10.0.0.{i}"))
    resp = logged_client.post("/api/v1/checks/run", json={})
    assert resp.status_code == 200
    results = resp.json()
    assert len(results) == 5
    assert all(r["status"] == "success" for r in results)
    assert logged_client.get("/api/v1/results").json()["total"] == 5


def test_manual_run_unknown_target(logged_client: TestClient):
    resp = logged_client.post("/api/v1/checks/run", json={"target_id": "nonexistent"})
    assert resp.status_code == 404


def test_results_filter_by_target_name(logged_client: TestClient, fake_checker, no_scheduler):
    fake_checker(status="success", message="ok")
    logged_client.post("/api/v1/targets", json=_payload(name="路由器", ip="192.168.1.1"))
    logged_client.post("/api/v1/targets", json=_payload(name="公网", ip="8.8.8.8"))
    logged_client.post("/api/v1/checks/run", json={})

    r = logged_client.get("/api/v1/results", params={"target_name": "路由器"}).json()
    assert r["total"] == 1
    assert r["results"][0]["target_name"] == "路由器"

    missing = logged_client.get(
        "/api/v1/results", params={"target_name": "不存在"}
    ).json()
    assert missing["total"] == 0


def test_results_filter_ip_wildcard(logged_client: TestClient, fake_checker, no_scheduler):
    fake_checker(status="success", message="ok")
    logged_client.post("/api/v1/targets", json=_payload(name="a", ip="192.168.1.1"))
    logged_client.post("/api/v1/targets", json=_payload(name="b", ip="192.168.2.2"))
    logged_client.post("/api/v1/checks/run", json={})

    assert logged_client.get("/api/v1/results", params={"ip": "192.168.*"}).json()["total"] == 2
    assert logged_client.get("/api/v1/results", params={"ip": "192.168.1.*"}).json()["total"] == 1


def test_app_settings_crud_and_resize(logged_client: TestClient, fake_checker, no_scheduler):
    fake_checker(status="success", message="ok")
    logged_client.post("/api/v1/targets", json=_payload())
    logged_client.post("/api/v1/targets", json=_payload(name="b", ip="1.1.1.1"))
    logged_client.post("/api/v1/checks/run", json={})
    assert logged_client.get("/api/v1/results").json()["total"] == 2

    cfg = logged_client.get("/api/v1/settings/app").json()
    assert cfg["result_max_records"] == 50000
    assert cfg["ping_count"] == 4
    assert cfg["connect_timeout"] == 3.0
    assert cfg["http_timeout"] == 5.0

    updated = logged_client.put(
        "/api/v1/settings/app", json={**cfg, "result_max_records": 100}
    )
    assert updated.status_code == 200
    assert updated.json()["result_max_records"] == 100
    # 上限修改立即生效（存储层同步更新）
    assert logged_client.app.state.result_store.max_records == 100
    assert logged_client.get("/api/v1/results").json()["total"] == 2

    resp = logged_client.put("/api/v1/settings/app", json={**cfg, "ping_count": 0})
    assert resp.status_code == 422


def test_target_ping_count_field(logged_client: TestClient):
    created = logged_client.post(
        "/api/v1/targets",
        json={**_payload(method="ping"), "ping_count": 7},
    )
    assert created.status_code == 201
    assert created.json()["ping_count"] == 7

    updated = logged_client.put(
        f"/api/v1/targets/{created.json()['id']}", json={"ping_count": None}
    )
    assert updated.status_code == 200
    assert updated.json()["ping_count"] is None


async def test_run_check_resolves_ping_count(tmp_path, monkeypatch):
    """ping 发包数：目标单独设置优先，未设置用全局默认。"""
    settings = Settings(
        _env_file=None,
        data_dir=tmp_path / "data",
        access_code="test-access-code",
        jwt_secret="x" * 40,
    )
    store = ConfigStore(settings.data_dir)
    result_store = ResultStore(settings.data_dir / "results.jsonl", 100)
    scheduler = Scheduler(store, result_store, Notifier(store), settings)

    captured: dict[str, int] = {}

    class _Fake:
        def __init__(self, outcome):
            self.outcome = outcome

        async def check(self, target):
            return self.outcome

    def fake_build(target, default_timeout, ping_count, success_codes=None):
        captured["ping_count"] = ping_count
        from app.checkers.base import CheckOutcome

        return _Fake(CheckOutcome("success", "ok", latency_ms=1.0))

    monkeypatch.setattr("app.scheduler.build_checker", fake_build)

    await store.update_app_settings(AppSettings(ping_count=6))
    await store.upsert_target(
        Target(id="t1", ip="127.0.0.1", check_method="ping")
    )
    await scheduler.run_check(await store.get_target("t1"))
    assert captured["ping_count"] == 6  # 未设置 → 全局默认

    await store.upsert_target(
        Target(id="t2", ip="127.0.0.1", check_method="ping", ping_count=9)
    )
    await scheduler.run_check(await store.get_target("t2"))
    assert captured["ping_count"] == 9  # 单独设置覆盖全局


def test_webhook_settings_crud(logged_client: TestClient):
    cfg = logged_client.get("/api/v1/settings/webhook").json()
    assert cfg["enabled"] is True
    assert cfg["url"] is None
    assert cfg["fail_threshold"] == 3

    updated = logged_client.put(
        "/api/v1/settings/webhook",
        json={"enabled": True, "url": "https://gotify.example.com/message", "fail_threshold": 5},
    )
    assert updated.status_code == 200
    assert updated.json()["fail_threshold"] == 5

    cfg = logged_client.get("/api/v1/settings/webhook").json()
    assert cfg["url"] == "https://gotify.example.com/message"
    assert cfg["fail_threshold"] == 5


def test_webhook_settings_validation(logged_client: TestClient):
    resp = logged_client.put(
        "/api/v1/settings/webhook", json={"enabled": True, "url": "x", "fail_threshold": 0}
    )
    assert resp.status_code == 422


def test_target_interval_zero_allowed(logged_client: TestClient, fake_checker):
    """check_interval=0 表示关闭定时检查，应允许创建。"""
    fake_checker(status="success", message="ok")
    payload = _payload()
    payload["check_interval"] = 0
    created = logged_client.post("/api/v1/targets", json=payload)
    assert created.status_code == 201
    assert created.json()["check_interval"] == 0
    # 手动检查仍可用
    run = logged_client.post("/api/v1/checks/run", json={})
    assert run.status_code == 200
    assert run.json()[0]["status"] == "success"


def test_webhook_test_push_no_url(logged_client: TestClient):
    resp = logged_client.post("/api/v1/settings/webhook/test", json={})
    assert resp.status_code == 400


def test_webhook_test_push_ok(logged_client: TestClient, monkeypatch):
    async def fake_send_test(url):
        assert url == "http://example.invalid/hook"
        return True, "HTTP 200"

    monkeypatch.setattr(logged_client.app.state.notifier, "send_test", fake_send_test)
    resp = logged_client.post(
        "/api/v1/settings/webhook/test", json={"url": "http://example.invalid/hook"}
    )
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


def test_webhook_test_push_failure(logged_client: TestClient, monkeypatch):
    async def fake_send_test(url):
        return False, "连接被拒绝"

    monkeypatch.setattr(logged_client.app.state.notifier, "send_test", fake_send_test)
    resp = logged_client.post("/api/v1/settings/webhook/test", json={"url": "http://x"})
    assert resp.status_code == 502
    assert "连接被拒绝" in resp.json()["detail"]


async def test_reconcile_skips_manual_only_target(tmp_path):
    """check_interval=0 或未启用的目标都不应创建定时任务。"""
    settings = Settings(
        _env_file=None,
        data_dir=tmp_path / "data",
        access_code="test-access-code",
        jwt_secret="x" * 40,
    )
    store = ConfigStore(settings.data_dir)
    result_store = ResultStore(settings.data_dir / "results.jsonl", 50)
    scheduler = Scheduler(store, result_store, Notifier(store), settings)
    await store.upsert_target(
        Target(id="t0", ip="127.0.0.1", check_method="port", check_interval=0, port=80)
    )
    await store.upsert_target(
        Target(
            id="t1",
            ip="127.0.0.1",
            check_method="port",
            check_interval=60,
            port=80,
            enabled=False,
        )
    )
    await scheduler.reconcile()
    assert scheduler._tasks == {}
    await scheduler.stop()


def test_stats_trend(logged_client: TestClient, fake_checker, no_scheduler):
    fake_checker(status="success", message="ok")
    logged_client.post("/api/v1/targets", json=_payload())
    logged_client.post("/api/v1/checks/run", json={})

    trend = logged_client.get("/api/v1/stats/trend", params={"hours": 24}).json()
    assert len(trend["buckets"]) == 24
    assert trend["buckets"][-1]["total"] == 1
    assert trend["buckets"][-1]["success"] == 1


def test_stats_summary(logged_client: TestClient, fake_checker, no_scheduler):
    fake_checker(status="fail", message="超时了")
    logged_client.post("/api/v1/targets", json=_payload())
    logged_client.post("/api/v1/checks/run", json={})

    stats = logged_client.get("/api/v1/stats/summary").json()
    assert stats["total_targets"] == 1
    assert stats["enabled_targets"] == 1
    assert stats["last_total_checks"] == 1
    assert stats["last_fail"] == 1
    ts = stats["target_status"][0]
    assert ts["last_status"] == "fail"
    # 近 24h 可用率字段（全部失败 → 0%）
    assert ts["uptime_pct"] == 0.0
    assert ts["uptime_total"] == 1


def test_results_filter_by_check_method(logged_client, fake_checker, no_scheduler):
    """check_method 筛选：单值与逗号分隔多值均生效（含导出接口）。"""
    fake_checker(status="success", message="ok")
    logged_client.post("/api/v1/targets", json=_payload(name="p1", ip="8.8.8.1", method="ping"))
    logged_client.post("/api/v1/targets", json=_payload(name="h1", ip="8.8.8.2", method="http"))
    logged_client.post("/api/v1/checks/run", json={})

    only_http = logged_client.get(
        "/api/v1/results", params={"check_method": "http"}
    ).json()
    assert only_http["total"] == 1
    assert only_http["results"][0]["check_method"] == "http"

    multi = logged_client.get(
        "/api/v1/results", params={"check_method": "ping,http"}
    ).json()
    assert multi["total"] == 2

    export = logged_client.get(
        "/api/v1/results/export.json", params={"check_method": "dns"}
    ).json()
    assert export == []


def test_results_multi_value_filters(logged_client, fake_checker, no_scheduler):
    """status / target_id 支持逗号分隔多值筛选（前端多选）。"""
    fake_checker(status="timeout", message="slow")
    logged_client.post("/api/v1/targets", json=_payload(name="mv-1", ip="8.8.8.1"))
    logged_client.post("/api/v1/checks/run", json={})
    fake_checker(status="success", message="ok")
    logged_client.post("/api/v1/targets", json=_payload(name="mv-2", ip="8.8.8.2"))
    logged_client.post("/api/v1/checks/run", json={})

    # 第一次 run 1 条 timeout；第二次 run 全部目标（timeout + success）共 3 条
    data = logged_client.get("/api/v1/results", params={"status": "timeout,success"}).json()
    assert data["total"] == 3
    data = logged_client.get("/api/v1/results", params={"status": "success"}).json()
    assert data["total"] == 2

    targets = logged_client.get("/api/v1/targets").json()
    t1, t2 = targets[0]["id"], targets[1]["id"]
    data = logged_client.get(
        "/api/v1/results", params={"target_id": f"{t1},{t2}"}
    ).json()
    assert data["total"] == 3

    # 名称多选：回归（曾因精确匹配单个字符串导致返回空）
    names = ",".join(t["name"] for t in targets)
    data = logged_client.get("/api/v1/results", params={"target_name": names}).json()
    assert data["total"] == 3


def test_stats_summary_respects_stats_window(
    logged_client: TestClient, fake_checker, no_scheduler
):
    """仪表盘统计窗口读全局配置：修改 app.stats_window 后 summary 同步。"""
    fake_checker(status="success", message="ok")
    logged_client.post("/api/v1/targets", json=_payload())
    logged_client.post("/api/v1/checks/run", json={})

    stats = logged_client.get("/api/v1/stats/summary").json()
    assert stats["stats_window"] == 50

    cfg = logged_client.get("/api/v1/settings/app").json()
    cfg["stats_window"] = 10
    assert logged_client.put("/api/v1/settings/app", json=cfg).status_code == 200
    stats = logged_client.get("/api/v1/stats/summary").json()
    assert stats["stats_window"] == 10


def test_results_api_datetime_range_filter(logged_client: TestClient, fake_checker, no_scheduler):
    """start_at/end_at 参数须经 API 生效（回归：端点曾未声明参数被静默忽略）。"""
    from datetime import datetime, timedelta

    fake_checker(status="success", message="ok")
    logged_client.post("/api/v1/targets", json=_payload())
    assert logged_client.post("/api/v1/checks/run", json={}).status_code == 200

    assert logged_client.get("/api/v1/results").json()["total"] >= 1
    # 未来起始时间 → 无结果
    future = logged_client.get("/api/v1/results", params={"start_at": "2099-01-01T00:00:00"}).json()
    assert future["total"] == 0
    # 过去的结束时间 → 无结果
    past = logged_client.get("/api/v1/results", params={"end_at": "2000-01-01T00:00:00"}).json()
    assert past["total"] == 0
    # 覆盖多天的范围（昨天 00:00 → 明天 23:59）→ 命中今天的结果（跨日场景）
    today = datetime.now().astimezone()
    start = (today - timedelta(days=1)).strftime("%Y-%m-%dT00:00:00")
    end = (today + timedelta(days=1)).strftime("%Y-%m-%dT23:59:59")
    span = logged_client.get(
        "/api/v1/results", params={"start_at": start, "end_at": end}
    ).json()
    assert span["total"] >= 1


def test_s3_settings_crud(logged_client: TestClient):
    """S3 配置：默认值、保存、凭据落 secrets.json、密钥不回读、留空不改、必填校验。"""
    resp = logged_client.get("/api/v1/settings/s3")
    assert resp.status_code == 200
    data = resp.json()
    assert data["enabled"] is False
    assert data["has_credentials"] is False
    assert "access_id" not in data and "access_key" not in data  # 密钥明文永不回读

    payload = {
        "enabled": True,
        "endpoint": "https://s3.example.com",
        "bucket": "cc-data",
        "region": "us-east-1",
        "datapath": "connection-checker/",
        "access_id": "minioadmin",
        "access_key": "minioadmin123",
    }
    resp = logged_client.put("/api/v1/settings/s3", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["enabled"] is True
    assert data["endpoint"] == "https://s3.example.com"
    assert data["region"] == "us-east-1"
    assert data["has_credentials"] is True

    # 配置与凭据落盘位置分离
    data_dir = logged_client.app.state.settings.data_dir
    cfg_raw = json.loads((data_dir / "config.json").read_text(encoding="utf-8"))
    assert cfg_raw["s3"]["bucket"] == "cc-data"
    secrets_raw = json.loads((data_dir / "secrets.json").read_text(encoding="utf-8"))
    assert secrets_raw["s3_access_id"] == "minioadmin"
    assert secrets_raw["s3_access_key"] == "minioadmin123"

    # 凭据字段留空 = 不修改
    resp = logged_client.put(
        "/api/v1/settings/s3",
        json={
            "enabled": True,
            "endpoint": "https://s3.example.com",
            "bucket": "cc-data",
            "datapath": "cc/",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["has_credentials"] is True
    secrets_raw = json.loads((data_dir / "secrets.json").read_text(encoding="utf-8"))
    assert secrets_raw["s3_access_key"] == "minioadmin123"

    # 启用 S3 但缺必填字段 → 422
    resp = logged_client.put("/api/v1/settings/s3", json={"enabled": True, "bucket": "x"})
    assert resp.status_code == 422

    # 可以清除凭据（显式传空字符串）
    resp = logged_client.put(
        "/api/v1/settings/s3",
        json={
            "enabled": True,
            "endpoint": "https://s3.example.com",
            "bucket": "cc-data",
            "datapath": "cc/",
            "access_id": "",
            "access_key": "",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["has_credentials"] is False


def test_check_error_logs_error_level(logged_client, fake_checker, no_scheduler, caplog):
    """检查返回 error 时记录 ERROR 级日志（需求：报错便于及时排查）。"""
    import logging

    fake_checker(status="error", message="权限不足")
    logged_client.post("/api/v1/targets", json=_payload())
    with caplog.at_level(logging.ERROR):
        resp = logged_client.post("/api/v1/checks/run", json={})
    assert resp.status_code == 200
    assert any("Check error" in r.message for r in caplog.records)


def test_check_fail_timeout_log_warning(logged_client, fake_checker, no_scheduler, caplog):
    """检查失败/超时记录 WARN 级日志，成功保持 INFO。"""
    import logging

    logged_client.post("/api/v1/targets", json=_payload(name="warn-目标"))

    for status, msg_prefix in (("fail", "Check failed"), ("timeout", "Check timed out")):
        fake_checker(status=status, message=f"fake-{status}")
        with caplog.at_level(logging.WARNING):
            resp = logged_client.post("/api/v1/checks/run", json={})
        assert resp.status_code == 200
        assert any(
            r.message.startswith(msg_prefix) and "warn-目标" in r.message
            for r in caplog.records
        )
        caplog.clear()

    # 成功不产生 WARN 日志
    fake_checker(status="success", message="ok")
    with caplog.at_level(logging.WARNING):
        logged_client.post("/api/v1/checks/run", json={})
    assert not any("Check " in r.message for r in caplog.records)


def test_check_debug_nodes_logged(logged_client, fake_checker, no_scheduler, caplog):
    """关键节点在 DEBUG 级记录：开始检查、结果存储。"""
    import logging

    fake_checker(status="success", message="ok")
    logged_client.post("/api/v1/targets", json=_payload())
    with caplog.at_level(logging.DEBUG):
        logged_client.post("/api/v1/checks/run", json={})
    msgs = [r.message for r in caplog.records]
    assert any(m.startswith("Starting check") for m in msgs)
    assert any(m.startswith("Result stored") for m in msgs)


def _bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _generate_token(logged_client: TestClient) -> str:
    # 写方法强制 JSON 内容类型，POST 无 body 也需显式带 JSON
    resp = logged_client.post("/api/v1/settings/api-token/generate", json={})
    assert resp.status_code == 200
    return resp.json()["token"]


def test_api_token_flow(logged_client: TestClient):
    """API Token：生成后 Bearer 可用，重新生成旧 token 失效，删除后禁用。"""
    assert logged_client.get("/api/v1/settings/api-token").json()["token"] is None

    token = _generate_token(logged_client)
    assert token

    assert logged_client.get("/api/v1/targets", headers=_bearer(token)).status_code == 200
    assert (
        logged_client.get("/api/v1/targets", headers=_bearer("wrong")).status_code == 401
    )
    assert logged_client.get("/api/v1/targets").status_code == 200  # cookie 仍可用

    secrets_raw = json.loads(
        (logged_client.app.state.settings.data_dir / "secrets.json").read_text(encoding="utf-8")
    )
    assert secrets_raw["api_token"] == token

    new_token = _generate_token(logged_client)
    assert new_token != token
    assert logged_client.get("/api/v1/targets", headers=_bearer(token)).status_code == 401
    assert logged_client.get("/api/v1/targets", headers=_bearer(new_token)).status_code == 200

    assert logged_client.delete("/api/v1/settings/api-token").status_code == 200
    assert logged_client.get("/api/v1/settings/api-token").json()["token"] is None
    assert logged_client.get("/api/v1/targets", headers=_bearer(new_token)).status_code == 401


def test_api_token_requires_json_content_type(logged_client: TestClient):
    """token 认证路径同样执行 CSRF 415 检查（写方法需 JSON）。"""
    token = _generate_token(logged_client)
    resp = logged_client.post(
        "/api/v1/checks/run",
        content="{}",
        headers={**_bearer(token), "content-type": "text/plain"},
    )
    assert resp.status_code == 415


def test_brand_icon_validation(logged_client: TestClient):
    """品牌图标：正方形 data URI 可保存，非正方形/非法来源被 422 拒绝。"""
    import base64
    import struct

    def png_uri(w: int, h: int) -> str:
        sig = b"\x89PNG\r\n\x1a\n"
        ihdr = b"\x00\x00\x00\x0dIHDR" + struct.pack(">II", w, h) + b"\x08\x06\x00\x00\x00"
        return "data:image/png;base64," + base64.b64encode(sig + ihdr).decode()

    cfg = logged_client.get("/api/v1/settings/app").json()
    cfg["brand_icon"] = png_uri(32, 32)
    resp = logged_client.put("/api/v1/settings/app", json=cfg)
    assert resp.status_code == 200
    assert resp.json()["brand_icon"] == cfg["brand_icon"]

    cfg["brand_icon"] = png_uri(32, 16)
    resp = logged_client.put("/api/v1/settings/app", json=cfg)
    assert resp.status_code == 422
    assert "正方形" in resp.json()["detail"]

    cfg["brand_icon"] = "not-an-icon"
    resp = logged_client.put("/api/v1/settings/app", json=cfg)
    assert resp.status_code == 422

    # 清空回默认
    cfg["brand_icon"] = None
    resp = logged_client.put("/api/v1/settings/app", json=cfg)
    assert resp.status_code == 200
    assert resp.json()["brand_icon"] is None


def test_s3_dependent_settings_rejected_without_s3(logged_client: TestClient):
    """依赖 S3 的全局设置（日志保留=upload / 记录存储=both/s3）在 S3 未配置时被 422 拒绝。"""
    cfg = logged_client.get("/api/v1/settings/app").json()

    cfg["log_cleanup_mode"] = "upload"
    resp = logged_client.put("/api/v1/settings/app", json=cfg)
    assert resp.status_code == 422
    assert "S3" in resp.json()["detail"]

    cfg["log_cleanup_mode"] = "delete"
    cfg["storage_mode"] = "both"
    resp = logged_client.put("/api/v1/settings/app", json=cfg)
    assert resp.status_code == 422

    # 配置好 S3 后允许保存
    logged_client.put(
        "/api/v1/settings/s3",
        json={
            "enabled": True,
            "endpoint": "http://s3.local:9000",
            "bucket": "cc",
            "datapath": "data/",
            "access_id": "minioadmin",
            "access_key": "minioadmin123",
        },
    )
    cfg["storage_mode"] = "s3"
    assert logged_client.put("/api/v1/settings/app", json=cfg).status_code == 200

    # 只配置了配置项但缺凭据 → 仍拒绝（显式清空凭据）
    cfg["storage_mode"] = "local"
    logged_client.put("/api/v1/settings/app", json=cfg)
    logged_client.put(
        "/api/v1/settings/s3",
        json={
            "enabled": True,
            "endpoint": "http://s3.local:9000",
            "bucket": "cc",
            "datapath": "data/",
            "access_id": "",
            "access_key": "",
        },
    )
    cfg["log_cleanup_mode"] = "upload"
    resp = logged_client.put("/api/v1/settings/app", json=cfg)
    assert resp.status_code == 422


def test_s3_test_endpoint(logged_client: TestClient, monkeypatch):
    """S3 测试连接：缺配置 400、成功 ok、bucket 不存在提示、连接失败 502。"""
    resp = logged_client.post("/api/v1/settings/s3/test", json={})
    assert resp.status_code == 400

    logged_client.put(
        "/api/v1/settings/s3",
        json={
            "enabled": True,
            "endpoint": "http://s3.local:9000",
            "bucket": "cc",
            "datapath": "data/",
            "access_id": "minioadmin",
            "access_key": "minioadmin123",
        },
    )

    monkeypatch.setattr("app.s3_storage.S3Storage.bucket_exists", lambda self: True)
    resp = logged_client.post("/api/v1/settings/s3/test", json={})
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    assert "存在" in resp.json()["info"]

    monkeypatch.setattr("app.s3_storage.S3Storage.bucket_exists", lambda self: False)
    resp = logged_client.post("/api/v1/settings/s3/test", json={})
    assert resp.json()["ok"] is True
    assert "不存在" in resp.json()["info"]

    def boom(self):
        raise RuntimeError("connection refused")

    monkeypatch.setattr("app.s3_storage.S3Storage.bucket_exists", boom)
    resp = logged_client.post("/api/v1/settings/s3/test", json={})
    assert resp.status_code == 502

    # 携带表单配置（未保存）测试；凭据留空回退已保存
    monkeypatch.setattr("app.s3_storage.S3Storage.bucket_exists", lambda self: True)
    resp = logged_client.post(
        "/api/v1/settings/s3/test",
        json={"endpoint": "http://other:9000", "bucket": "other-bucket"},
    )
    assert resp.status_code == 200
