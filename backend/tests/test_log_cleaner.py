"""日志自动清理测试：删除/上传 S3 模式、无 S3 配置跳过、失败保留重试。"""

import logging
from datetime import datetime, timedelta

from app.config import Settings
from app.log_cleaner import LogCleaner
from app.models import AppSettings, S3Config
from app.s3_storage import S3Storage, endpoint_parts
from app.storage import ConfigStore, SecretsStore


def _make_logs(log_dir, *days_ago: int):
    log_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for d in days_ago:
        date = (datetime.now().astimezone() - timedelta(days=d)).strftime("%Y-%m-%d")
        p = log_dir / f"app-{date}.log"
        p.write_text(f"log {date}", encoding="utf-8")
        paths.append(p)
    return paths


def _fixtures(tmp_path):
    settings = Settings(_env_file=None, data_dir=tmp_path / "data")
    store = ConfigStore(settings.data_dir)
    secrets = SecretsStore(settings.data_dir)
    cleaner = LogCleaner(store, secrets, settings)
    return cleaner, store, secrets, settings


async def test_delete_mode_removes_old_logs(tmp_path):
    cleaner, store, _, settings = _fixtures(tmp_path)
    old, recent = _make_logs(settings.data_dir / "logs", 40, 5)
    await store.update_app_settings(
        AppSettings(log_cleanup_mode="delete", log_retention_days=30)
    )
    await cleaner.run_once()
    assert not old.exists()
    assert recent.exists()


async def test_none_mode_keeps_all_logs(tmp_path):
    cleaner, store, _, settings = _fixtures(tmp_path)
    old = _make_logs(settings.data_dir / "logs", 40)[0]
    await store.update_app_settings(
        AppSettings(log_cleanup_mode="none", log_retention_days=30)
    )
    await cleaner.run_once()
    assert old.exists()


async def test_upload_mode_uploads_then_removes(tmp_path, monkeypatch, caplog):
    cleaner, store, secrets, settings = _fixtures(tmp_path)
    old, recent = _make_logs(settings.data_dir / "logs", 40, 5)
    secrets.s3_access_id = "minioadmin"
    secrets.s3_access_key = "minioadmin123"
    await store.update_s3_config(
        S3Config(enabled=True, endpoint="http://s3.local:9000", bucket="cc", datapath="data/")
    )
    await store.update_app_settings(
        AppSettings(log_cleanup_mode="upload", log_retention_days=30)
    )

    uploaded: list[tuple[str, str]] = []

    def fake_upload(self, object_name, file_path):
        uploaded.append((object_name, str(file_path)))

    monkeypatch.setattr(S3Storage, "upload_file", fake_upload)
    with caplog.at_level(logging.INFO):
        await cleaner.run_once()

    assert len(uploaded) == 1
    assert uploaded[0][0] == "data/logs/" + old.name
    assert not old.exists()  # 上传成功后删除本地
    assert recent.exists()
    assert any("Uploaded old log" in r.message for r in caplog.records)


async def test_upload_mode_failure_keeps_local(tmp_path, monkeypatch, caplog):
    cleaner, store, secrets, settings = _fixtures(tmp_path)
    old = _make_logs(settings.data_dir / "logs", 40)[0]
    secrets.s3_access_id = "minioadmin"
    secrets.s3_access_key = "minioadmin123"
    await store.update_s3_config(
        S3Config(enabled=True, endpoint="http://s3.local:9000", bucket="cc", datapath="data/")
    )
    await store.update_app_settings(
        AppSettings(log_cleanup_mode="upload", log_retention_days=30)
    )

    def fake_upload(self, object_name, file_path):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(S3Storage, "upload_file", fake_upload)
    with caplog.at_level(logging.ERROR):
        await cleaner.run_once()

    assert old.exists()  # 失败保留本地，下次重试
    assert any("Failed to upload log" in r.message for r in caplog.records)


async def test_upload_mode_without_s3_warns_and_keeps(tmp_path, caplog):
    cleaner, store, _, settings = _fixtures(tmp_path)
    old = _make_logs(settings.data_dir / "logs", 40)[0]
    await store.update_app_settings(
        AppSettings(log_cleanup_mode="upload", log_retention_days=30)
    )
    with caplog.at_level(logging.WARNING):
        await cleaner.run_once()
    assert old.exists()
    assert any("not configured or credentials missing" in r.message for r in caplog.records)


def test_endpoint_parts():
    assert endpoint_parts("https://s3.example.com") == ("s3.example.com", True)
    assert endpoint_parts("http://localhost:9000") == ("localhost:9000", False)
    assert endpoint_parts("s3.example.com:9000") == ("s3.example.com:9000", True)
