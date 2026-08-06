"""ICMP Ping 检查，基于 ping3（纯 Python，跨平台）。需要原始套接字权限。"""
import asyncio

import ping3
from ping3.errors import DestinationUnreachable, HostUnknown, PingError, Timeout

from app.checkers.base import BaseChecker, CheckOutcome
from app.models import Target


class PingChecker(BaseChecker):
    """逐次调用 ping3.ping，统计延迟与丢包率。count 取自 settings。"""

    def __init__(self, timeout: float, count: int = 4) -> None:
        super().__init__(timeout)
        self.count = count

    async def check(self, target: Target) -> CheckOutcome:
        samples: list[float] = []
        last_error: str | None = None
        for _ in range(self.count):
            try:
                rtt = await asyncio.to_thread(ping3.ping, target.ip, timeout=self.timeout, unit="s")
                if rtt is not None:
                    samples.append(rtt * 1000.0)
            except Timeout:
                pass
            except HostUnknown:
                return CheckOutcome("fail", "无法解析主机名")
            except DestinationUnreachable:
                return CheckOutcome("fail", "目标不可达")
            except PermissionError:
                return CheckOutcome(
                    "error", "缺少原始套接字权限（容器需 CAP_NET_RAW）"
                )
            except (PingError, OSError) as e:
                last_error = str(e)

        if last_error and not samples:
            return CheckOutcome("error", f"ping 失败: {last_error}")

        sent = self.count
        received = len(samples)
        loss_pct = (sent - received) / sent * 100
        if received == 0:
            return CheckOutcome("timeout", f"ping 超时（丢包 {loss_pct:.0f}%）")

        avg = sum(samples) / len(samples)
        extra = {
            "packet_loss_pct": round(loss_pct, 1),
            "min_ms": round(min(samples), 1),
            "max_ms": round(max(samples), 1),
        }
        if loss_pct > 50:
            return CheckOutcome(
                "fail",
                f"连接不稳定，丢包率 {loss_pct:.0f}%（平均延迟 {avg:.0f}ms）",
                latency_ms=round(avg, 1),
                extra=extra,
            )
        return CheckOutcome(
            "success",
            f"平均延迟 {avg:.0f}ms，丢包率 {loss_pct:.0f}%",
            latency_ms=round(avg, 1),
            extra=extra,
        )
