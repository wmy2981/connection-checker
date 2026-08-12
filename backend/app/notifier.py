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
        # 告警触发时的连续失败次数，恢复通知里告知故障规模
        self._last_fail_count: dict[str, int] = {}

    async def observe(self, result: CheckResult) -> None:
        """根据一条新检查结果更新失败计数并在跨越阈值时发送通知。

        连续失败计数独立于告警配置：即使 webhook 未启用也跟踪（供统计接口展示），
        通知推送则按配置与目标开关决定。
        """
        tid = result.target_id
        if result.status == "success":
            self._fails[tid] = 0
            logger.debug(
                "Target %s consecutive fails reset to 0",
                result.target_name or result.ip,
            )
        else:
            self._fails[tid] = self._fails.get(tid, 0) + 1

        cfg = await self.config_store.get_webhook_config()
        if not cfg.enabled or not cfg.url:
            return
        target = await self.config_store.get_target(tid)
        if target is not None and not target.notify_enabled:
            return  # 该目标单独关闭了告警（含恢复通知）
        if result.status == "success":
            if tid in self._alerted:
                self._alerted.discard(tid)
                fails = self._last_fail_count.pop(tid, 0)
                summary = (
                    f"连续失败 {fails} 次后已恢复正常" if fails else "连接已恢复正常"
                )
                logger.info(
                    "Target %s recovered after %d consecutive fails, sending recovery notification",
                    result.target_name or result.ip,
                    fails,
                )
                await self._send("恢复", summary, result, cfg.url)
            return

        n = self._fails[tid]
        logger.debug(
            "Target %s consecutive fails=%d threshold=%d",
            result.target_name or result.ip,
            n,
            cfg.fail_threshold,
        )
        # 计数独立于告警配置增长（webhook 关闭期间也可能超过阈值），
        # 重新启用后首次跨阈值仍触发；已告警过的连续故障不重复推送
        if n >= cfg.fail_threshold and tid not in self._alerted:
            self._alerted.add(tid)
            self._last_fail_count[tid] = n
            logger.warning(
                "Target %s failed %d times in a row, sending alert",
                result.target_name or result.ip,
                n,
            )
            await self._send("告警", f"连续 {n} 次检查失败", result, cfg.url)

    def consecutive_fails(self, target_id: str) -> int:
        """当前连续失败次数（未失败过为 0），供统计接口展示。"""
        return self._fails.get(target_id, 0)

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
