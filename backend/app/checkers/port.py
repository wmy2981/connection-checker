"""TCP 端口连通性检查，基于 asyncio.open_connection。"""
import asyncio
import time

from app.checkers.base import BaseChecker, CheckOutcome
from app.models import Target


class PortChecker(BaseChecker):
    async def check(self, target: Target) -> CheckOutcome:
        port = target.port or 80
        started = time.monotonic()
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(target.ip, port), timeout=self.timeout
            )
        except (asyncio.TimeoutError, TimeoutError):  # noqa: UP024
            return CheckOutcome("timeout", f"端口 {port} 连接超时")
        except OSError as e:
            return CheckOutcome("fail", f"端口 {port} 连接失败: {e.strerror or e}")
        except Exception as e:  # noqa: BLE001
            return CheckOutcome("error", f"端口 {port} 检查出错: {e}")

        elapsed = (time.monotonic() - started) * 1000
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:  # noqa: BLE001
            pass
        return CheckOutcome(
            "success",
            f"端口 {port} 开放",
            latency_ms=round(elapsed, 1),
            extra={"port": port},
        )
