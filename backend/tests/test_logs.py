"""日志系统测试：级别解析、每日文件、查看/导出 API。"""

import logging

import pytest
from pydantic import ValidationError

from app.logging_setup import DailyFileHandler, apply_level, parse_level
from app.models import AppSettings


def test_parse_level():
    assert parse_level("DEBUG") == logging.DEBUG
    assert parse_level("warn") == logging.WARNING
    assert parse_level("ERROR") == logging.ERROR
    assert parse_level("bogus") == logging.INFO  # 未知级别回退 INFO


def test_apply_level_changes_root_level():
    apply_level("ERROR")
    assert logging.getLogger().getEffectiveLevel() == logging.ERROR
    apply_level("INFO")
    assert logging.getLogger().getEffectiveLevel() == logging.INFO


def test_daily_file_handler_writes_and_rolls(tmp_path, monkeypatch):
    import app.logging_setup as ls

    real_datetime = ls.datetime
    current = ["2026-08-10 10:00:00"]

    class FakeDateTime:
        @staticmethod
        def now():
            return real_datetime.strptime(current[0], "%Y-%m-%d %H:%M:%S")

        strptime = staticmethod(real_datetime.strptime)

    monkeypatch.setattr(ls, "datetime", FakeDateTime)

    handler = DailyFileHandler(tmp_path)
    handler.emit(logging.LogRecord("app.test", logging.INFO, "", 1, "hello", (), None))
    handler.emit(logging.LogRecord("app.test", logging.WARNING, "", 1, "world", (), None))
    files = sorted(tmp_path.glob("app-*.log"))
    assert len(files) == 1
    assert files[0].name == "app-2026-08-10.log"
    content = files[0].read_text(encoding="utf-8")
    assert "hello" in content and "world" in content
    assert "| INFO | app.test |" in content  # 新格式含来源段（文件:行号）
    assert "hello" in content.split("| app.test |", 1)[1]

    # 跨日：再次写入应切到新文件，且旧文件内容保留
    current[0] = "2026-08-11 00:00:00"
    handler.emit(logging.LogRecord("app.test", logging.INFO, "", 1, "next-day", (), None))
    files = sorted(tmp_path.glob("app-*.log"))
    assert [f.name for f in files] == ["app-2026-08-10.log", "app-2026-08-11.log"]
    assert "next-day" in (tmp_path / "app-2026-08-11.log").read_text(encoding="utf-8")
    handler.close()


def test_logs_api_level_filter(logged_client, no_scheduler):
    logging.getLogger("app.scheduler").info("logs-test-info")
    logging.getLogger("app.scheduler").warning("logs-test-warn")
    logging.getLogger("app.scheduler").error("logs-test-error")

    # 多选精确集合匹配；WARN 归一为 WARNING
    resp = logged_client.get("/api/v1/logs", params={"level": "WARN"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["results"][0]["level"] == "WARNING"

    # 多选集合：WARN,ERROR 只含这两个级别
    resp = logged_client.get("/api/v1/logs", params={"level": "WARN,ERROR"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 2
    levels = {r["level"] for r in data["results"] if "logs-test" in r["message"]}
    assert levels == {"WARNING", "ERROR"}

    # 全级别多选应包含 WARN,ERROR 的所有条目
    resp = logged_client.get("/api/v1/logs", params={"level": "DEBUG,INFO,WARN,ERROR"})
    assert resp.json()["total"] >= data["total"]


def test_logs_api_time_filter(logged_client):
    resp = logged_client.get("/api/v1/logs", params={"start": "2099-01-01"})
    assert resp.status_code == 200
    assert resp.json()["total"] == 0  # 未来时间范围不应命中


def test_logs_pagination_newest_first(logged_client):
    lg = logging.getLogger("app.test")
    for i in range(5):
        lg.warning(f"logs-page-{i}")
    resp = logged_client.get("/api/v1/logs", params={"level": "WARN", "page": 1, "page_size": 2})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["results"]) == 2
    assert data["page_size"] == 2
    assert data["pages"] >= 1
    assert data["results"][0]["time"] >= data["results"][1]["time"]  # 最新在前


def test_logs_multiline_traceback_merged(logged_client):
    lg = logging.getLogger("app.test")
    try:
        raise ValueError("logs-boom")
    except ValueError:
        lg.exception("logs-with-traceback")
    resp = logged_client.get("/api/v1/logs", params={"level": "ERROR"})
    assert resp.status_code == 200
    hit = [r for r in resp.json()["results"] if "logs-with-traceback" in r["message"]]
    assert hit and "Traceback" in hit[0]["message"]


def test_logs_export(logged_client):
    logging.getLogger("app.test").warning("logs-export-me")
    resp = logged_client.get("/api/v1/logs/export", params={"level": "WARN"})
    assert resp.status_code == 200
    assert "logs-export-me" in resp.text
    assert "attachment" in resp.headers["content-disposition"]


def test_logs_api_source_filter(logged_client, no_scheduler):
    """按来源筛选：文件（新格式行含 source）与模块名（旧格式行兼容）均生效。"""
    logging.getLogger("app.scheduler").info("logs-source-scheduler")
    logging.getLogger("app.notifier").warning("logs-source-notifier")

    resp = logged_client.get("/api/v1/logs", params={"source": "test_logs"})
    assert resp.status_code == 200
    data = resp.json()
    hit = [r for r in data["results"] if "logs-source-" in r["message"]]
    assert hit, "source 筛选未命中新格式行"
    assert all(r["source"] for r in hit), "新格式行应携带 source 字段"
    assert all(r["source"].split(":", 1)[0].endswith(".py") for r in hit)

    resp = logged_client.get("/api/v1/logs", params={"source": "app.scheduler"})
    assert resp.status_code == 200
    assert any(r["name"] == "app.scheduler" for r in resp.json()["results"])

    # 不匹配的来源应返回空
    resp = logged_client.get("/api/v1/logs", params={"source": "no-such-source"})
    assert resp.json()["total"] == 0


def test_logs_sources_endpoint(logged_client, no_scheduler):
    """来源枚举接口返回去重后的文件名/模块名。"""
    logging.getLogger("app.scheduler").warning("logs-sources-probe")
    resp = logged_client.get("/api/v1/logs/sources")
    assert resp.status_code == 200
    sources = resp.json()["sources"]
    assert any("test_logs" in s for s in sources)
    assert sources == sorted(sources)  # 去重且有序


def test_log_sources_cache_keyed_by_data_dir(tmp_path):
    """来源 TTL 缓存按数据目录分键：不同实例互不串扰（回归：全局单键会污染）。"""
    from fastapi.testclient import TestClient

    from app.api import logs as logs_api
    from app.config import Settings
    from app.main import create_app

    def _client(dirpath):
        s = Settings(
            _env_file=None,
            data_dir=dirpath,
            access_code="cache-test",
            jwt_secret="x" * 40,
        )
        with TestClient(create_app(s)) as c:
            c.post("/api/v1/auth/login", json={"access_code": "cache-test"})
            return c

    c1 = _client(tmp_path / "d1")
    c2 = _client(tmp_path / "d2")
    assert c1.get("/api/v1/logs/sources").status_code == 200
    assert c2.get("/api/v1/logs/sources").status_code == 200
    # 两个新实例各自独立缓存键（不受前序测试已填充键的影响）
    keys = set(logs_api._source_cache)
    assert {str(tmp_path / "d1" / "logs"), str(tmp_path / "d2" / "logs")} <= keys


def test_app_settings_log_level_validation():
    assert AppSettings().log_level == "INFO"
    assert AppSettings(log_level="DEBUG").log_level == "DEBUG"
    with pytest.raises(ValidationError):
        AppSettings(log_level="bogus")


def test_uvicorn_access_level_pinned_to_debug(tmp_path):
    """HTTP 访问日志固定 DEBUG 级，热更新不改变该固定行为。"""
    from app.logging_setup import configure

    configure(tmp_path, "INFO")
    assert logging.getLogger("uvicorn").getEffectiveLevel() == logging.INFO
    assert logging.getLogger("uvicorn.access").getEffectiveLevel() == logging.DEBUG

    apply_level("ERROR")
    assert logging.getLogger("uvicorn").getEffectiveLevel() == logging.ERROR
    assert logging.getLogger("uvicorn.access").getEffectiveLevel() == logging.DEBUG
