from fastapi.testclient import TestClient


def _payload(name: str = "测试", method: str = "ping", ip: str = "8.8.8.8") -> dict:
    return {"name": name, "ip": ip, "check_method": method, "check_interval": 60}


def test_login_wrong_code(client: TestClient):
    resp = client.post("/api/v1/auth/login", json={"access_code": "nope"})
    assert resp.status_code == 401


def test_me_unauthenticated(client: TestClient):
    assert client.get("/api/v1/auth/me").json()["authenticated"] is False


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


def test_manual_run_unknown_target(logged_client: TestClient):
    resp = logged_client.post("/api/v1/checks/run", json={"target_id": "nonexistent"})
    assert resp.status_code == 404


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
