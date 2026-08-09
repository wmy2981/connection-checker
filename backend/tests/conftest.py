from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.checkers.base import CheckOutcome
from app.config import Settings
from app.main import create_app


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        data_dir=tmp_path / "data",
        access_code="test-access-code",
        jwt_secret="test-jwt-secret-0123456789abcdefghijklmnopqrstuvwxyz",
    )


@pytest.fixture
def app(settings: Settings):
    return create_app(settings)


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        yield c


@pytest.fixture
def logged_client(client: TestClient):
    resp = client.post("/api/v1/auth/login", json={"access_code": "test-access-code"})
    assert resp.status_code == 200
    return client


class _FakeChecker:
    def __init__(self, outcome: CheckOutcome) -> None:
        self.outcome = outcome

    async def check(self, target):  # noqa: ANN001
        return self.outcome


@pytest.fixture
def fake_checker(monkeypatch):
    """替换 scheduler 的 build_checker，使检查不触网、结果可控。"""

    def _patch(status: str = "success", message: str = "ok", latency_ms: float | None = 10.0):
        outcome = CheckOutcome(status=status, message=message, latency_ms=latency_ms)
        monkeypatch.setattr("app.scheduler.build_checker", lambda *a, **k: _FakeChecker(outcome))

    return _patch


@pytest.fixture
def no_scheduler(monkeypatch):
    """禁用 reconcile，避免新建目标触发定时任务的立即检查，保证结果计数确定。"""

    async def _noop(self):  # noqa: ANN001
        pass

    monkeypatch.setattr("app.scheduler.Scheduler.reconcile", _noop)
