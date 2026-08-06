"""Webhook 告警：连续失败达到阈值触发，恢复时通知。兼容 Gotify / 企业微信 / 自建服务。"""
import logging
from datetime import datetime, timezone

import httpx

from app.models import CheckResult

logger = logging.getLogger(__name__)


class Notifier:
    def __init__(self, webhook_url: str | None, fail_threshold: int) -> None:
        self.webhook_url = webhook_url
        self.fail_threshold = max(1, fail_threshold)
        self._fails: dict[str, int] = {}
        self._alerted: set[str] = set()

    async def observe(self, result: CheckResult) -> None:
        """根据一条新检查结果更新失败计数并在跨越阈值时发送通知。"""
        if not self.webhook_url:
            return
        tid = result.target_id
        if result.status == "success":
            was_alerted = tid in self._alerted
            self._fails[tid] = 0
            if was_alerted:
                self._alerted.discard(tid)
                await self._send("恢复", "连接已恢复正常", result)
            return

        n = self._fails.get(tid, 0) + 1
        self._fails[tid] = n
        if n == self.fail_threshold:
            self._alerted.add(tid)
            await self._send("告警", f"连续 {n} 次检查失败", result)

    async def _send(self, kind: str, summary: str, result: CheckResult) -> None:
        payload = {
            "title": f"[{kind}] {result.target_name or result.ip}",
            "message": f"{summary}: {result.message}",
            "event": "connection_checker",
            "target": {
                "id": result.target_id,
                "name": result.target_name,
                "ip": result.ip,
                "check_method": result.check_method,
                "status": result.status,
                "latency_ms": result.latency_ms,
            },
            "ts": datetime.now(timezone.utc).isoformat(),
        }
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.post(self.webhook_url, json=payload)
                resp.raise_for_status()
        except Exception as e:  # noqa: BLE001
            logger.error("Webhook 通知失败: %s", e)
