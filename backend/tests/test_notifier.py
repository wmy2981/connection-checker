from app.models import CheckResult, Target, WebhookConfig
from app.notifier import Notifier
from app.storage import ConfigStore


def _result(tid: str, status: str, message: str = "x") -> CheckResult:
    return CheckResult(
        target_id=tid,
        target_name=f"目标{tid}",
        ip="8.8.8.8",
        check_method="ping",
        status=status,
        message=message,
    )


async def test_notifier_alert_on_threshold_and_recover(tmp_path, monkeypatch):
    store = ConfigStore(tmp_path / "data")
    await store.update_webhook_config(
        WebhookConfig(enabled=True, url="http://example.invalid", fail_threshold=2)
    )
    notifier = Notifier(store)
    sent: list[tuple[str, str]] = []

    async def _send(kind, summary, result, url):
        sent.append((kind, summary))

    monkeypatch.setattr(notifier, "_send", _send)

    await notifier.observe(_result("t1", "fail"))
    assert sent == []
    await notifier.observe(_result("t1", "fail"))
    assert sent == [("告警", "连续 2 次检查失败")]
    # 已达阈值的后续失败不再重复告警
    await notifier.observe(_result("t1", "fail"))
    assert len(sent) == 1
    # 成功后发恢复通知
    await notifier.observe(_result("t1", "success"))
    assert sent[-1][0] == "恢复"


async def test_notifier_disabled_or_no_url(tmp_path, monkeypatch):
    store = ConfigStore(tmp_path / "data")
    await store.update_webhook_config(
        WebhookConfig(enabled=False, url="http://example.invalid", fail_threshold=2)
    )
    notifier = Notifier(store)
    sent: list[tuple[str, str]] = []

    async def _send(kind, summary, result, url):
        sent.append((kind, summary))

    monkeypatch.setattr(notifier, "_send", _send)

    await notifier.observe(_result("t1", "fail"))
    await notifier.observe(_result("t1", "fail"))
    assert sent == []


async def test_notifier_target_notify_disabled(tmp_path, monkeypatch):
    """目标关闭 notify_enabled 后，告警与恢复通知都不推送。"""
    store = ConfigStore(tmp_path / "data")
    await store.update_webhook_config(
        WebhookConfig(enabled=True, url="http://example.invalid", fail_threshold=2)
    )
    notifier = Notifier(store)
    sent: list[tuple[str, str]] = []

    async def _send(kind, summary, result, url):
        sent.append((kind, summary))

    monkeypatch.setattr(notifier, "_send", _send)

    await store.upsert_target(
        Target(id="t1", ip="8.8.8.8", check_method="ping", notify_enabled=False)
    )
    await notifier.observe(_result("t1", "fail"))
    await notifier.observe(_result("t1", "fail"))
    await notifier.observe(_result("t1", "success"))
    assert sent == []


async def test_notifier_uses_updated_threshold(tmp_path, monkeypatch):
    store = ConfigStore(tmp_path / "data")
    await store.update_webhook_config(
        WebhookConfig(enabled=True, url="http://example.invalid", fail_threshold=3)
    )
    notifier = Notifier(store)
    sent: list[tuple[str, str]] = []

    async def _send(kind, summary, result, url):
        sent.append((kind, summary))

    monkeypatch.setattr(notifier, "_send", _send)

    await notifier.observe(_result("t1", "fail"))
    # 运行中调低阈值，下一次失败应立即触发
    await store.update_webhook_config(
        WebhookConfig(enabled=True, url="http://example.invalid", fail_threshold=2)
    )
    await notifier.observe(_result("t1", "fail"))
    assert sent == [("告警", "连续 2 次检查失败")]
