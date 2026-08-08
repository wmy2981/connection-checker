import asyncio
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from ping3.errors import HostUnknown

from app.checkers.http import HttpChecker
from app.checkers.ping import PingChecker
from app.checkers.port import PortChecker
from app.models import Target


def _target(method: str, **overrides) -> Target:
    data = {"id": "t1", "ip": "127.0.0.1", "check_method": method, "check_interval": 60}
    data.update(overrides)
    return Target(**data)


async def test_ping_success(monkeypatch):
    def fake_ping(*a, **k):
        return 0.012

    monkeypatch.setattr("ping3.ping", fake_ping)
    outcome = await PingChecker(timeout=1.0, count=3).check(_target("ping"))
    assert outcome.status == "success"
    assert outcome.latency_ms == pytest.approx(12.0, abs=1)
    assert outcome.extra["packet_loss_pct"] == 0


async def test_ping_all_timeout(monkeypatch):
    def fake_ping(*a, **k):
        return None

    monkeypatch.setattr("ping3.ping", fake_ping)
    outcome = await PingChecker(timeout=1.0, count=3).check(_target("ping"))
    assert outcome.status == "timeout"


async def test_ping_host_unknown(monkeypatch):
    def fake_ping(*a, **k):
        raise HostUnknown("no such host")

    monkeypatch.setattr("ping3.ping", fake_ping)
    outcome = await PingChecker(timeout=1.0, count=3).check(_target("ping"))
    assert outcome.status == "fail"


async def test_ping_partial_loss(monkeypatch):
    calls = {"n": 0}

    def fake_ping(*a, **k):
        calls["n"] += 1
        return 0.02 if calls["n"] % 2 == 0 else None

    monkeypatch.setattr("ping3.ping", fake_ping)
    outcome = await PingChecker(timeout=1.0, count=4).check(_target("ping"))
    assert outcome.status == "success"
    assert outcome.extra["packet_loss_pct"] == 50


async def test_port_success():
    server = await asyncio.start_server(
        lambda r, w: (w.close(), None), "127.0.0.1", 0
    )
    port = server.sockets[0].getsockname()[1]
    try:
        outcome = await PortChecker(1.0).check(_target("port", port=port))
        assert outcome.status == "success"
        assert outcome.extra["port"] == port
    finally:
        server.close()
        await server.wait_closed()


async def test_port_closed():
    # 拿一个空闲端口（绑定后立即释放）
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    outcome = await PortChecker(0.5).check(_target("port", port=port))
    # Windows 环回上可能表现为超时而非快速拒绝，只断言非成功
    assert outcome.status != "success"


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *a):  # noqa: ANN002
        pass


def _http_server() -> tuple[ThreadingHTTPServer, int]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    return server, server.server_address[1]


async def test_http_success():
    server, port = _http_server()
    try:
        outcome = await HttpChecker(1.0).check(_target("http", port=port, url_path="/"))
        assert outcome.status == "success"
        assert outcome.extra["http_status"] == 200
    finally:
        server.shutdown()


async def test_http_unexpected_status():
    server, port = _http_server()
    try:
        outcome = await HttpChecker(1.0, success_codes=[404]).check(
            _target("http", port=port, url_path="/")
        )
        assert outcome.status == "fail"
        assert outcome.extra["http_status"] == 200
    finally:
        server.shutdown()


async def test_http_connection_refused():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    outcome = await HttpChecker(0.5).check(_target("http", port=port, url_path="/"))
    assert outcome.status != "success"


class _SlowHandler(BaseHTTPRequestHandler):
    """响应头立即发送，body 每 0.4s 发一块。httpx 的分阶段空闲超时无法兜住总耗时。"""

    def do_GET(self):
        try:
            self.send_response(200)
            self.send_header("Content-Length", "30")
            self.end_headers()
            for _ in range(3):
                time.sleep(0.4)
                self.wfile.write(b"x" * 10)
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass  # 客户端超时断开属预期

    def log_message(self, *a):  # noqa: ANN002
        pass


async def test_http_timeout_is_total():
    """自定义超时应作为总耗时上限，而非分阶段空闲超时。"""
    server = ThreadingHTTPServer(("127.0.0.1", 0), _SlowHandler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        started = time.monotonic()
        outcome = await HttpChecker(0.5).check(
            _target("http", port=server.server_address[1], url_path="/")
        )
        elapsed = time.monotonic() - started
        assert outcome.status == "timeout"
        assert elapsed < 1.0, f"总耗时 {elapsed:.2f}s 超过了超时上限 0.5s"
    finally:
        server.shutdown()
