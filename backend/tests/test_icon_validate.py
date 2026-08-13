"""品牌图标校验测试：位图/矢量宽高解析、正方形校验、data URI 与 URL 来源。"""

import base64
import struct

import pytest

from app.icon_validate import validate_icon


def _png(w: int, h: int) -> bytes:
    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = b"\x00\x00\x00\x0dIHDR" + struct.pack(">II", w, h) + b"\x08\x06\x00\x00\x00"
    return sig + ihdr


def _jpeg(w: int, h: int) -> bytes:
    sof0 = b"\xff\xc0\x00\x0b\x08" + struct.pack(">HH", h, w) + b"\x03\x01\x22\x00\x02\x11\x01\x03"
    header = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    return header + sof0 + b"\xff\xd9"


def _gif(w: int, h: int) -> bytes:
    return b"GIF89a" + struct.pack("<HH", w, h) + b"\x00\x00\x00"


def _webp_vp8x(w: int, h: int) -> bytes:
    return (
        b"RIFF\x00\x00\x00\x00WEBPVP8X"
        + b"\x00" * 8  # chunk size(4) + flags(1) + reserved(3)
        + (w - 1).to_bytes(3, "little")
        + (h - 1).to_bytes(3, "little")
    )


def _svg(width: str | None = None, height: str | None = None, viewbox: str | None = None) -> str:
    attrs = ""
    if width is not None:
        attrs += f' width="{width}"'
    if height is not None:
        attrs += f' height="{height}"'
    if viewbox is not None:
        attrs += f' viewBox="{viewbox}"'
    return f'<svg xmlns="http://www.w3.org/2000/svg"{attrs}></svg>'


def _data_uri(mime: str, data: bytes) -> str:
    return f"data:{mime};base64,{base64.b64encode(data).decode()}"


def test_png_square_and_non_square():
    assert validate_icon(_data_uri("image/png", _png(16, 16))) == (16, 16)
    with pytest.raises(ValueError, match="正方形"):
        validate_icon(_data_uri("image/png", _png(16, 9)))


def test_jpeg_gif_webp_bitmaps():
    assert validate_icon(_data_uri("image/jpeg", _jpeg(32, 32))) == (32, 32)
    assert validate_icon(_data_uri("image/gif", _gif(8, 8))) == (8, 8)
    assert validate_icon(_data_uri("image/webp", _webp_vp8x(24, 24))) == (24, 24)
    with pytest.raises(ValueError, match="正方形"):
        validate_icon(_data_uri("image/webp", _webp_vp8x(24, 12)))


def test_svg_square():
    svg_uri = lambda svg: _data_uri("image/svg+xml", svg.encode())  # noqa: E731
    assert validate_icon(svg_uri(_svg(width="64", height="64"))) == (64, 64)
    assert validate_icon(svg_uri(_svg(viewbox="0 0 100 100"))) == (100, 100)
    with pytest.raises(ValueError, match="正方形"):
        validate_icon(_data_uri("image/svg+xml", _svg(viewbox="0 0 100 50").encode()))
    with pytest.raises(ValueError, match="缺少"):
        validate_icon(_data_uri("image/svg+xml", _svg().encode()))


def test_invalid_source():
    with pytest.raises(ValueError, match="仅支持"):
        validate_icon("plain-text-icon")
    with pytest.raises(ValueError, match="base64"):
        validate_icon("data:image/png;base64,!!!not-base64!!!")
    with pytest.raises(ValueError, match="不支持的图片格式"):
        validate_icon(_data_uri("image/png", b"not-a-real-image-at-all"))


def test_url_source(monkeypatch):
    class FakeResp:
        headers = {"content-type": "image/png"}
        content = _png(20, 20)

        def raise_for_status(self):
            pass

    monkeypatch.setattr("httpx.get", lambda url, timeout, follow_redirects: FakeResp())
    assert validate_icon("https://example.com/icon.png") == (20, 20)


def test_url_fetch_failure(monkeypatch):
    import httpx

    def boom(url, timeout, follow_redirects):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr("httpx.get", boom)
    with pytest.raises(ValueError, match="下载失败"):
        validate_icon("https://example.com/nope.png")
