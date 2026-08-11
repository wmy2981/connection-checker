"""DNS 解析检查，基于标准库 getaddrinfo（默认同时查 A / AAAA）。"""
import asyncio
import logging
import socket
import time

from app.checkers.base import BaseChecker, CheckOutcome
from app.models import Target

logger = logging.getLogger(__name__)


class DnsChecker(BaseChecker):
    async def check(self, target: Target) -> CheckOutcome:
        host = target.ip
        started = time.monotonic()
        try:
            infos = await asyncio.wait_for(
                asyncio.to_thread(socket.getaddrinfo, host, None), timeout=self.timeout
            )
        except (asyncio.TimeoutError, TimeoutError):  # noqa: UP024
            logger.debug("DNS %s: lookup timeout after %.1fs", host, self.timeout)
            return CheckOutcome("timeout", f"解析 {host} 超时")
        except socket.gaierror as e:
            logger.debug("DNS %s: lookup failed: %s", host, e.strerror or e)
            return CheckOutcome("fail", f"解析 {host} 失败: {e.strerror or e}")
        except OSError as e:
            logger.debug("DNS %s: lookup failed: %s", host, e.strerror or e)
            return CheckOutcome("fail", f"解析 {host} 失败: {e.strerror or e}")
        except Exception as e:  # noqa: BLE001
            logger.debug("DNS %s: error=%s", host, e)
            return CheckOutcome("error", f"DNS 检查出错: {e}")

        elapsed = (time.monotonic() - started) * 1000
        addresses = sorted({item[4][0] for item in infos})
        if not addresses:
            logger.debug("DNS %s: no addresses resolved", host)
            return CheckOutcome("fail", f"解析 {host} 无结果")
        logger.debug(
            "DNS %s: resolved=%d addresses=%s in %.1fms",
            host,
            len(addresses),
            addresses[:5],
            elapsed,
        )
        display = "、".join(addresses[:5]) + (" 等" if len(addresses) > 5 else "")
        return CheckOutcome(
            "success",
            f"解析成功：{display}",
            latency_ms=round(elapsed, 1),
            extra={
                "resolved_ip": addresses,
                "resolved_count": len(addresses),
                "dns_lookup_ms": round(elapsed, 1),
            },
        )
