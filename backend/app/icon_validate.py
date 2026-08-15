"""品牌图标校验：支持 base64 data URI 与任意 URL，要求正方形（宽=高）。

位图（PNG/JPEG/GIF/WebP）用标准库解析文件头拿宽高，SVG 解析 width/height/viewBox，
零新增依赖。非正方形或无法解析时抛 ValueError，由调用方决定拒绝保存。
"""
import base64
import logging
import re
import struct
import xml.etree.ElementTree as ET

logger = logging.getLogger(__name__)

_DATA_URI_RE = re.compile(r"^data:([^;,]+);base64,(.+)$", re.S)


def parse_data_uri(value: str) -> tuple[str, bytes]:
    """解析 base64 data URI，返回 (mime, 解码字节)；不合法抛 ValueError。"""
    m = _DATA_URI_RE.match(value)
    if not m:
        raise ValueError("无效的 data URI，应为 data:<mime>;base64,<内容>")
    mime = m.group(1).lower()
    try:
        data = base64.b64decode(m.group(2), validate=True)
    except Exception as e:  # noqa: BLE001
        raise ValueError(f"base64 解码失败: {e}") from None
    if not data:
        raise ValueError("图片数据为空")
    return mime, data


def image_ext(mime: str, data: bytes) -> str:
    """按 data URI mime 与内容 magic 推断文件扩展名（不含点）；无法识别抛 ValueError。"""
    if mime == "image/svg+xml":
        return "svg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[:3] == b"\xff\xd8\xff":
        return "jpg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    raise ValueError("无法识别图片格式")


def validate_icon(value: str) -> tuple[int, int]:
    """解析并校验图标来源，返回 (width, height)；不合法或非正方形抛 ValueError。"""
    value = value.strip()
    if value.startswith("data:"):
        mime, data = parse_data_uri(value)
    elif value.startswith(("http://", "https://")):
        mime, data = _fetch(value)
    else:
        raise ValueError("仅支持 base64 data URI 或 http(s) URL")
    size = _check_square(mime, data)
    logger.info("Brand icon validated: %dx%d (%s)", size[0], size[1], mime)
    return size


def _fetch(url: str) -> tuple[str, bytes]:
    import httpx

    try:
        resp = httpx.get(url, timeout=10, follow_redirects=True)
        resp.raise_for_status()
    except httpx.HTTPError as e:
        raise ValueError(f"图片下载失败: {e}") from None
    mime = resp.headers.get("content-type", "").split(";")[0].strip().lower()
    if mime == "image/svg+xml" or (not mime and url.lower().endswith(".svg")):
        return "image/svg+xml", resp.content
    return mime or "application/octet-stream", resp.content


def _check_square(mime: str, data: bytes) -> tuple[int, int]:
    if mime == "image/svg+xml":
        w, h = _parse_svg(data.decode("utf-8", errors="replace"))
    else:
        w, h = _parse_bitmap(data)
    if w != h:
        raise ValueError(f"图标必须是正方形，当前 {w}x{h}")
    return w, h


def _parse_bitmap(data: bytes) -> tuple[int, int]:
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        if len(data) < 24:
            raise ValueError("PNG 数据不完整")
        w, h = struct.unpack(">II", data[16:24])
    elif data[:3] == b"\xff\xd8\xff":
        w, h = _jpeg_size(data)
    elif data[:6] in (b"GIF87a", b"GIF89a"):
        if len(data) < 10:
            raise ValueError("GIF 数据不完整")
        w, h = struct.unpack("<HH", data[6:10])
    elif data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        w, h = _webp_size(data)
    else:
        raise ValueError("不支持的图片格式（支持 PNG/JPEG/GIF/WebP/SVG）")
    return w, h


def _jpeg_size(data: bytes) -> tuple[int, int]:
    """JPEG 尺寸：逐段扫描到 SOF 标记（0xC0-0xCF，排除 C4/C8/CC）。"""
    i = 2
    while i + 9 < len(data):
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        if marker in (
            0xC0,
            0xC1,
            0xC2,
            0xC3,
            0xC5,
            0xC6,
            0xC7,
            0xC9,
            0xCA,
            0xCB,
            0xCD,
            0xCE,
            0xCF,
        ):
            h, w = struct.unpack(">HH", data[i + 5 : i + 9])
            return w, h
        if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7:
            i += 2
            continue
        length = struct.unpack(">H", data[i + 2 : i + 4])[0]
        i += 2 + length
    raise ValueError("JPEG 尺寸解析失败")


def _webp_size(data: bytes) -> tuple[int, int]:
    chunk = data[12:16]
    if chunk == b"VP8 ":
        if len(data) < 30:
            raise ValueError("WebP 数据不完整")
        w = struct.unpack("<H", data[26:28])[0] & 0x3FFF
        h = struct.unpack("<H", data[28:30])[0] & 0x3FFF
        return w, h
    if chunk == b"VP8L":
        if len(data) < 25:
            raise ValueError("WebP 数据不完整")
        b = data[21:25]
        w = 1 + (b[0] | ((b[1] & 0x3F) << 8))
        h = 1 + ((b[1] >> 6) | (b[2] << 2) | ((b[3] & 0x0F) << 10))
        return w, h
    if chunk == b"VP8X":
        if len(data) < 30:
            raise ValueError("WebP 数据不完整")
        w = 1 + int.from_bytes(data[24:27], "little")
        h = 1 + int.from_bytes(data[27:30], "little")
        return w, h
    raise ValueError("WebP 格式解析失败")


def _parse_svg(text: str) -> tuple[int, int]:
    try:
        root = ET.fromstring(text)
    except ET.ParseError as e:
        raise ValueError(f"SVG 解析失败: {e}") from None
    w = _svg_num(root.get("width"))
    h = _svg_num(root.get("height"))
    vb = root.get("viewBox")
    if vb:
        parts = [float(x) for x in re.findall(r"[\d.]+", vb)]
        if len(parts) >= 4:
            w, h = parts[2], parts[3]
    if not w or not h:
        raise ValueError("SVG 缺少 width/height/viewBox，无法校验")
    return int(w), int(h)


def _svg_num(s: str | None) -> float:
    m = re.search(r"[\d.]+", s or "")
    return float(m.group()) if m else 0.0
