"""HTTP(S) 状态码检查，基于 httpx。"""
import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any

import httpx

from app.checkers.base import BaseChecker, CheckOutcome
from app.models import Target

logger = logging.getLogger(__name__)

# 响应体读取上限（字节）：状态码检查不需要完整 body，避免大文件拖慢检查与占内存
BODY_READ_LIMIT = 1_000_000


def _default_port(scheme: str) -> int:
    return 443 if scheme == "https" else 80


def _issuer_name(cert: dict) -> str | None:
    """从 getpeercert() 的 issuer 嵌套元组里提取常用名称。"""
    for pairs in cert.get("issuer", ()):
        for key, value in pairs:
            if key in ("organizationName", "commonName"):
                return value
    return None


def _tls_info(ssl_object: Any) -> dict[str, Any]:
    """提取 TLS 版本、加密套件与证书信息；任何一项取不到都静默跳过。"""
    info: dict[str, Any] = {}
    try:
        version = ssl_object.version()
        if version:
            info["version"] = version
        cipher = ssl_object.cipher()
        if cipher:
            info["cipher"] = cipher[0]
        cert = ssl_object.getpeercert()
        if cert:
            issuer = _issuer_name(cert)
            if issuer:
                info["issuer"] = issuer
            not_after = cert.get("notAfter")
            if not_after:
                try:
                    expiry = datetime.strptime(
                        not_after, "%b %d %H:%M:%S %Y GMT"
                    ).replace(tzinfo=timezone.utc)
                    info["not_after"] = expiry.isoformat()
                    info["days_remaining"] = (expiry - datetime.now(timezone.utc)).days
                except ValueError:
                    pass
    except (ValueError, OSError):
        pass
    return info


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

        async def _fetch() -> tuple[httpx.Response, bytes, float, float]:
            async with httpx.AsyncClient(timeout=None, follow_redirects=True) as client:
                req = client.build_request("GET", url)
                resp = await client.send(req, stream=True)
                t_headers = time.monotonic()
                body = bytearray()
                async for chunk in resp.aiter_bytes():
                    body.extend(chunk)
                    if len(body) >= BODY_READ_LIMIT:
                        break
                t_body = time.monotonic()
                await resp.aclose()
                return resp, bytes(body), t_headers, t_body

        try:
            # httpx 的 float timeout 是分阶段空闲超时（connect/read 各自计时），
            # 对慢速流式响应的服务器总耗时可能远超设定值。用 wait_for 施加总超时上限。
            resp, body, t_headers, t_body = await asyncio.wait_for(
                _fetch(), timeout=self.timeout
            )
        except (asyncio.TimeoutError, TimeoutError):  # noqa: UP024
            logger.debug("HTTP %s: timeout after %.0fs", url, self.timeout)
            return CheckOutcome("timeout", f"请求 {url} 超时")
        except httpx.ConnectError:
            logger.debug("HTTP %s: connection failed", url)
            return CheckOutcome("fail", f"无法连接 {url}")
        except Exception as e:  # noqa: BLE001
            logger.debug("HTTP %s: error=%s", url, e)
            return CheckOutcome("error", f"HTTP 检查出错: {e}")

        elapsed = (time.monotonic() - started) * 1000
        extra: dict[str, Any] = {
            "url": url,
            "final_url": str(resp.url),
            "http_status": resp.status_code,
            "http_version": resp.http_version,
            "redirects": len(resp.history),
            # ttfb 含连接建立与重定向；总耗时与 latency_ms 一致
            "ttfb_ms": round((t_headers - started) * 1000, 1),
            "body_read_ms": round((t_body - t_headers) * 1000, 1),
            "total_ms": round((t_body - started) * 1000, 1),
            "content_type": resp.headers.get("content-type"),
            "response_size": len(body),
        }
        raw_length = resp.headers.get("content-length")
        if raw_length is not None:
            try:
                extra["content_length"] = int(raw_length)
            except ValueError:
                pass
        # HTTPS 时补充 TLS 证书信息（可提前发现即将过期）
        stream = resp.extensions.get("network_stream")
        if stream is not None:
            ssl_object = stream.get_extra_info("ssl_object")
            if ssl_object is not None:
                tls = _tls_info(ssl_object)
                if tls:
                    extra["tls"] = tls

        logger.debug(
            "HTTP %s: status=%d expected=%s latency=%.1fms ttfb=%.1fms size=%dB redirects=%d",
            url,
            resp.status_code,
            codes,
            elapsed,
            round((t_headers - started) * 1000, 1),
            len(body),
            len(resp.history),
        )
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
