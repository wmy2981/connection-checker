"""ICMP Ping 检查，基于 ping3（纯 Python，跨平台）。需要原始套接字权限。"""
import asyncio

import ping3
from ping3.errors import DestinationUnreachable, HostUnknown, PingError, Timeout

from app.checkers.base import BaseChecker, CheckOutcome
from app.models import Target


def _jitter_ms(samples: list[float]) -> float:
    """延迟抖动：连续样本差绝对值的平均，样本不足 2 个时为 0。"""
    if len(samples) < 2:
        return 0.0
    diffs = [abs(samples[i] - samples[i - 1]) for i in range(1, len(samples))]
    return round(sum(diffs) / len(diffs), 1)


def _stddev_ms(samples: list[float]) -> float:
    """样本标准差，样本不足 2 个时为 0。"""
    if len(samples) < 2:
        return 0.0
    avg = sum(samples) / len(samples)
    variance = sum((s - avg) ** 2 for s in samples) / len(samples)
    return round(variance**0.5, 1)


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
            "jitter_ms": _jitter_ms(samples),
            "stddev_ms": _stddev_ms(samples),
            "sent": sent,
            "received": received,
            "samples_ms": [round(s, 1) for s in samples],
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
