"""TCP 端口连通性检查，基于 asyncio.open_connection。"""
import asyncio
import time
from typing import Any

from app.checkers.base import BaseChecker, CheckOutcome
from app.models import Target


def _conn_info(writer: asyncio.StreamWriter) -> dict[str, Any]:
    """从连接的 extra_info 提取远端/本地地址信息，取不到就静默跳过。"""
    info: dict[str, Any] = {}
    peername = writer.get_extra_info("peername")
    if isinstance(peername, tuple) and len(peername) >= 2:
        info["remote_ip"] = peername[0]
        info["remote_port"] = peername[1]
        info["family"] = "IPv6" if ":" in peername[0] else "IPv4"
    sockname = writer.get_extra_info("sockname")
    if isinstance(sockname, tuple) and len(sockname) >= 2:
        info["local_ip"] = sockname[0]
        info["local_port"] = sockname[1]
    return info


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
        extra = _conn_info(writer)
        extra["port"] = port
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:  # noqa: BLE001
            pass
        return CheckOutcome(
            "success",
            f"端口 {port} 开放",
            latency_ms=round(elapsed, 1),
            extra=extra,
        )
