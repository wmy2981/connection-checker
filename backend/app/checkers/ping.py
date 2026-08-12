"""ICMP Ping 检查，基于 ping3（纯 Python，跨平台）。需要原始套接字权限。"""
import asyncio
import logging

import ping3
from ping3.errors import DestinationUnreachable, HostUnknown, PingError, Timeout

from app.checkers.base import BaseChecker, CheckOutcome
from app.models import Target

logger = logging.getLogger(__name__)


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
    """并发调用 ping3.ping（每包一个线程），统计延迟与丢包率。count 取自 settings。

    并发使最坏耗时从 count × timeout 降为单次 timeout（慢网络/丢包下显著提速）。
    """

    def __init__(self, timeout: float, count: int = 4) -> None:
        super().__init__(timeout)
        self.count = count

    async def check(self, target: Target) -> CheckOutcome:
        async def _once() -> tuple[float | None, str | None]:
            """单包 ping；返回 (延迟ms, 错误标记)，超时为 (None, None)。"""
            try:
                rtt = await asyncio.to_thread(
                    ping3.ping, target.ip, timeout=self.timeout, unit="s"
                )
                if rtt is not None:
                    return rtt * 1000.0, None
                return None, None  # 超时
            except Timeout:
                return None, None
            except HostUnknown:
                return None, "host_unknown"
            except DestinationUnreachable:
                return None, "unreachable"
            except PermissionError:
                return None, "permission"
            except (PingError, OSError) as e:
                return None, str(e)

        outcomes = await asyncio.gather(*(_once() for _ in range(self.count)))
        samples = [r for r, _ in outcomes if r is not None]
        errors = [e for _, e in outcomes if e is not None]

        # 致命错误优先（与串行实现一致：任一包命中即按该错误判定）
        if "permission" in errors:
            logger.debug("Ping %s: no raw socket permission", target.ip)
            return CheckOutcome("error", "缺少原始套接字权限（容器需 CAP_NET_RAW）")
        if "host_unknown" in errors:
            logger.debug("Ping %s: hostname resolution failed", target.ip)
            return CheckOutcome("fail", "无法解析主机名")
        if "unreachable" in errors:
            logger.debug("Ping %s: destination unreachable", target.ip)
            return CheckOutcome("fail", "目标不可达")
        if errors and not samples:
            logger.debug("Ping %s: error=%s", target.ip, errors[0])
            return CheckOutcome("error", f"ping 失败: {errors[0]}")

        sent = self.count
        received = len(samples)
        loss_pct = (sent - received) / sent * 100
        if received == 0:
            logger.debug(
                "Ping %s: timeout, sent=%d received=%d loss=%.1f%%",
                target.ip,
                sent,
                received,
                loss_pct,
            )
            return CheckOutcome("timeout", f"ping 超时（丢包 {loss_pct:.0f}%）")

        avg = sum(samples) / len(samples)
        logger.debug(
            "Ping %s: sent=%d received=%d loss=%.1f%% avg=%.1fms min=%.1fms "
            "max=%.1fms jitter=%.1fms stddev=%.1fms samples=%s",
            target.ip,
            sent,
            received,
            loss_pct,
            avg,
            min(samples),
            max(samples),
            _jitter_ms(samples),
            _stddev_ms(samples),
            [round(s, 1) for s in samples],
        )
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
