import asyncio
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from ping3.errors import HostUnknown

from app.checkers.dns import DnsChecker
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
    assert outcome.extra["sent"] == 3
    assert outcome.extra["received"] == 3
    assert outcome.extra["samples_ms"] == [12.0, 12.0, 12.0]
    assert outcome.extra["jitter_ms"] == 0
    assert outcome.extra["stddev_ms"] == 0


async def test_ping_extra_jitter_stddev(monkeypatch):
    import threading

    samples = [0.01, 0.03, 0.01, 0.05]
    idx = 0
    lock = threading.Lock()  # 并发发包下保证取值顺序

    def fake_ping(*a, **k):
        nonlocal idx
        with lock:
            v = samples[idx]
            idx += 1
            return v

    monkeypatch.setattr("ping3.ping", fake_ping)
    outcome = await PingChecker(timeout=1.0, count=4).check(_target("ping"))
    assert outcome.status == "success"
    assert outcome.extra["min_ms"] == 10.0
    assert outcome.extra["max_ms"] == 50.0
    assert outcome.extra["jitter_ms"] == 26.7  # (|10-30|+|30-10|+|10-50|)/3
    assert outcome.extra["stddev_ms"] > 0


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
    import threading

    calls = {"n": 0}
    lock = threading.Lock()  # 并发发包下保证计数不丢

    def fake_ping(*a, **k):
        with lock:
            calls["n"] += 1
            return 0.02 if calls["n"] % 2 == 0 else None

    monkeypatch.setattr("ping3.ping", fake_ping)
    outcome = await PingChecker(timeout=1.0, count=4).check(_target("ping"))
    assert outcome.status == "success"
    assert outcome.extra["packet_loss_pct"] == 50


async def test_dns_success(monkeypatch):
    def fake_getaddrinfo(host, port, *a, **k):
        assert host == "example.com"
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0)),
            (
                socket.AF_INET6,
                socket.SOCK_STREAM,
                6,
                "",
                ("2606:2800:220:1:248:1893:25c8:1946", 0, 0, 0),
            ),
        ]

    monkeypatch.setattr("socket.getaddrinfo", fake_getaddrinfo)
    outcome = await DnsChecker(1.0).check(_target("dns", ip="example.com"))
    assert outcome.status == "success"
    assert outcome.extra["resolved_ip"] == [
        "2606:2800:220:1:248:1893:25c8:1946",
        "93.184.216.34",
    ]
    assert outcome.extra["resolved_count"] == 2


async def test_dns_host_not_found(monkeypatch):
    def fake_getaddrinfo(*a, **k):
        raise socket.gaierror(socket.EAI_NONAME, "Name or service not known")

    monkeypatch.setattr("socket.getaddrinfo", fake_getaddrinfo)
    outcome = await DnsChecker(1.0).check(_target("dns", ip="no-such-host.invalid"))
    assert outcome.status == "fail"


async def test_dns_timeout(monkeypatch):
    def slow_getaddrinfo(*a, **k):
        time.sleep(0.3)
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 0))]

    monkeypatch.setattr("socket.getaddrinfo", slow_getaddrinfo)
    outcome = await DnsChecker(0.05).check(_target("dns", ip="example.com"))
    assert outcome.status == "timeout"


async def test_port_success():
    server = await asyncio.start_server(
        lambda r, w: (w.close(), None), "127.0.0.1", 0
    )
    port = server.sockets[0].getsockname()[1]
    try:
        outcome = await PortChecker(1.0).check(_target("port", port=port))
        assert outcome.status == "success"
        assert outcome.extra["port"] == port
        assert outcome.extra["remote_ip"] == "127.0.0.1"
        assert outcome.extra["remote_port"] == port
        assert outcome.extra["family"] == "IPv4"
        assert outcome.extra["local_ip"] == "127.0.0.1"
        assert outcome.extra["local_port"] > 0
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


class _BigHandler(BaseHTTPRequestHandler):
    """Content-Length 声明 10MB 并持续发送；客户端应在读取上限后停止。"""

    def do_GET(self):
        try:
            self.send_response(200)
            self.send_header("Content-Length", str(10 * 1024 * 1024))
            self.end_headers()
            for _ in range(5):
                self.wfile.write(b"x" * (1024 * 1024))
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass  # 客户端读取到上限主动断开属预期

    def log_message(self, *a):  # noqa: ANN002
        pass


def _http_server() -> tuple[ThreadingHTTPServer, int]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    return server, server.server_address[1]


async def test_http_body_read_limit():
    """大响应体只读取到上限：状态码检查不被大文件拖慢，header 里的真实大小保留。"""
    server = ThreadingHTTPServer(("127.0.0.1", 0), _BigHandler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        outcome = await HttpChecker(5.0).check(
            _target("http", port=server.server_address[1], url_path="/")
        )
        assert outcome.status == "success"
        assert 0 < outcome.extra["response_size"] <= 1_100_000  # 略超上限的最后一个 chunk
        assert outcome.extra["content_length"] == 10 * 1024 * 1024
    finally:
        server.shutdown()


async def test_http_success():
    server, port = _http_server()
    try:
        outcome = await HttpChecker(1.0).check(_target("http", port=port, url_path="/"))
        assert outcome.status == "success"
        assert outcome.extra["http_status"] == 200
        assert outcome.extra["http_version"]  # "HTTP/1.0" 或 "HTTP/1.1"
        assert outcome.extra["redirects"] == 0
        assert outcome.extra["final_url"].endswith(f":{port}/")
        assert outcome.extra["ttfb_ms"] >= 0  # 本地快速响应在低精度计时器（如 Windows）下可能为 0
        assert outcome.extra["body_read_ms"] >= 0
        assert outcome.extra["total_ms"] == pytest.approx(outcome.latency_ms, abs=1)
        assert outcome.extra["response_size"] == 2  # body "ok"
        assert "tls" not in outcome.extra
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
