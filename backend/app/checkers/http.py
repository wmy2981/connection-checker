"""HTTP(S) 状态码检查，基于 httpx。"""
import asyncio
import time

import httpx

from app.checkers.base import BaseChecker, CheckOutcome
from app.models import Target


def _default_port(scheme: str) -> int:
    return 443 if scheme == "https" else 80


class HttpChecker(BaseChecker):
    def __init__(self, timeout: float, success_codes: list[int] | None = None) -> None:
        super().__init__(timeout)
        self.success_codes = success_codes

    async def check(self, target: Target) -> CheckOutcome:
        port = target.port or _default_port(target.scheme)
        url = f"{target.scheme}://{target.ip}:{port}{target.url_path}"
        codes = target.http_success_codes or self.success_codes
        if codes is None:
            codes = list(range(200, 400))

        started = time.monotonic()
        try:
            # httpx 的 float timeout 是分阶段空闲超时（connect/read 各自计时），
            # 对慢速流式响应的服务器总耗时可能远超设定值。用 wait_for 施加总超时上限。
            async with httpx.AsyncClient(timeout=None, follow_redirects=True) as client:
                resp = await asyncio.wait_for(client.get(url), timeout=self.timeout)
        except (asyncio.TimeoutError, TimeoutError):  # noqa: UP024
            return CheckOutcome("timeout", f"请求 {url} 超时")
        except httpx.ConnectError:
            return CheckOutcome("fail", f"无法连接 {url}")
        except Exception as e:  # noqa: BLE001
            return CheckOutcome("error", f"HTTP 检查出错: {e}")

        elapsed = (time.monotonic() - started) * 1000
        extra = {"url": url, "http_status": resp.status_code}
        if resp.status_code in codes:
            return CheckOutcome(
                "success",
                f"HTTP {resp.status_code} 状态码正常",
                latency_ms=round(elapsed, 1),
                extra=extra,
            )
        return CheckOutcome(
            "fail",
            f"HTTP {resp.status_code} 不在期望状态码 {codes} 内",
            latency_ms=round(elapsed, 1),
            extra=extra,
        )
