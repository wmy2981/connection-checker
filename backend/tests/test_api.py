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
    assert stats["target_status"][0]["last_status"] == "fail"


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
