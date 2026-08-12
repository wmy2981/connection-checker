"""Webhook 告警：连续失败达到阈值触发，恢复时通知。兼容 Gotify / 企业微信 / 自建服务。"""
import logging
from datetime import datetime, timezone

import httpx

from app.models import CheckResult
from app.storage import ConfigStore

logger = logging.getLogger(__name__)


class Notifier:
    def __init__(self, config_store: ConfigStore) -> None:
        self.config_store = config_store
        self._fails: dict[str, int] = {}
        self._alerted: set[str] = set()

    async def observe(self, result: CheckResult) -> None:
        """根据一条新检查结果更新失败计数并在跨越阈值时发送通知。"""
        cfg = await self.config_store.get_webhook_config()
        if not cfg.enabled or not cfg.url:
            return
        tid = result.target_id
        target = await self.config_store.get_target(tid)
        if target is not None and not target.notify_enabled:
            return  # 该目标单独关闭了告警（含恢复通知）
        if result.status == "success":
            was_alerted = tid in self._alerted
            self._fails[tid] = 0
            logger.debug(
                "Target %s consecutive fails reset to 0",
                result.target_name or result.ip,
            )
            if was_alerted:
                self._alerted.discard(tid)
                logger.info(
                    "Target %s recovered, sending recovery notification",
                    result.target_name or result.ip,
                )
                await self._send("恢复", "连接已恢复正常", result, cfg.url)
            return

        n = self._fails.get(tid, 0) + 1
        self._fails[tid] = n
        logger.debug(
            "Target %s consecutive fails=%d threshold=%d",
            result.target_name or result.ip,
            n,
            cfg.fail_threshold,
        )
        if n == cfg.fail_threshold:
            self._alerted.add(tid)
            logger.warning(
                "Target %s failed %d times in a row, sending alert",
                result.target_name or result.ip,
                n,
            )
            await self._send("告警", f"连续 {n} 次检查失败", result, cfg.url)

    async def send_test(self, url: str) -> tuple[bool, str]:
        """向 Webhook 发送一条测试消息，返回 (是否成功, 详情)。"""
        payload = {
            "title": "[测试] 连接检查工具",
            "message": "这是一条测试推送，用于验证 Webhook 配置是否可用。",
            "event": "connection_checker_test",
            "ts": datetime.now(timezone.utc).isoformat(),
        }
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.post(url, json=payload)
                resp.raise_for_status()
            return True, f"HTTP {resp.status_code}"
        except httpx.HTTPStatusError as e:
            detail = (e.response.text or "")[:200]
            return False, f"HTTP {e.response.status_code}: {detail}"
        except Exception as e:  # noqa: BLE001
            return False, str(e) or e.__class__.__name__

    async def _send(self, kind: str, summary: str, result: CheckResult, url: str) -> None:
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
                resp = await client.post(url, json=payload)
                resp.raise_for_status()
        except Exception as e:  # noqa: BLE001
            logger.error("Webhook notification failed: %s", e)
