from app.checkers.base import BaseChecker, CheckOutcome
from app.checkers.dns import DnsChecker
from app.checkers.http import HttpChecker
from app.checkers.ping import PingChecker
from app.checkers.port import PortChecker
from app.models import Target

__all__ = [
    "BaseChecker",
    "CheckOutcome",
    "PingChecker",
    "PortChecker",
    "HttpChecker",
    "DnsChecker",
]


def build_checker(
    target: Target,
    default_timeout: float,
    ping_count: int = 4,
    success_codes: list[int] | None = None,
) -> BaseChecker:
    """按目标检查方法构造检查器。"""
    timeout = target.timeout or default_timeout
    if target.check_method == "ping":
        return PingChecker(timeout, count=ping_count)
    if target.check_method == "port":
        return PortChecker(timeout)
    if target.check_method == "http":
        return HttpChecker(timeout, success_codes=success_codes)
    if target.check_method == "dns":
        return DnsChecker(timeout)
    raise ValueError(f"未知的检查方法: {target.check_method}")
