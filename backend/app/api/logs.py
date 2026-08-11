"""日志查看与导出：按时间范围、级别与来源过滤每日日志文件。

日志行格式（见 app/logging_setup.py）：
    2026-08-10 10:30:36,123 | INFO | app.scheduler | scheduler.py:72 | 消息文本
旧版格式无来源段（... | app.scheduler | 消息文本），解析时兼容。
traceback 等续行（不以时间戳开头）并入上一条的 message。
"""
import re
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import PlainTextResponse

from app.auth import require_auth

router = APIRouter(prefix="/logs", tags=["logs"], dependencies=[Depends(require_auth)])

_LEVELS = {"DEBUG": 10, "INFO": 20, "WARN": 30, "WARNING": 30, "ERROR": 40}

# 新格式：... | app.scheduler | scheduler.py:72 | message
_LINE_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3}) \| (\w+) \| ([\w.]+) \| ([\w.:]+:\d+) \| (.*)$"
)
# 旧格式（无来源段）：... | app.scheduler | message
_OLD_LINE_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3}) \| (\w+) \| ([\w.]+) \| (.*)$"
)


def _log_dir(request: Request) -> Path:
    return request.app.state.settings.data_dir / "logs"


def _parse_ts(ts: str) -> datetime:
    return datetime.strptime(ts, "%Y-%m-%d %H:%M:%S,%f")


def _normalize_ts(value: str) -> datetime:
    """接受 YYYY-MM-DD（当天 0 点）或 YYYY-MM-DDTHH:MM:SS（本地时间）。"""
    text = value.strip().replace("T", " ")
    try:
        return datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return datetime.strptime(text, "%Y-%m-%d")


def _entries(request: Request):
    """按时间正序产出日志条目；续行并入上一条的 message。

    source 为产生日志的「文件名:行号」（如 scheduler.py:72）；旧格式行无来源
    信息时为 None（保留 name 供按模块筛选）。
    """
    last: dict | None = None
    for f in sorted(_log_dir(request).glob("app-*.log")):
        try:
            fh = f.open(encoding="utf-8")
        except OSError:
            continue
        with fh:
            for raw in fh:
                line = raw.rstrip("\n")
                if not line.strip():
                    continue
                m = _LINE_RE.match(line)
                if m is not None:
                    ts, level, name, source, message = m.groups()
                    entry = {
                        "time": ts,
                        "level": level,
                        "name": name,
                        "source": source,
                        "message": message,
                    }
                else:
                    m = _OLD_LINE_RE.match(line)
                    if m is None:
                        if last is not None:
                            last["message"] += "\n" + line
                        continue
                    ts, level, name, message = m.groups()
                    entry = {
                        "time": ts,
                        "level": level,
                        "name": name,
                        "source": None,
                        "message": message,
                    }
                last = entry
                yield entry


def _filtered(
    request: Request,
    level: str | None,
    start: str | None,
    end: str | None,
    source: str | None = None,
):
    min_level = _LEVELS.get((level or "INFO").upper(), 20)
    start_dt = _normalize_ts(start) if start else None
    end_dt = _normalize_ts(end) if end else None
    src = source.strip().lower() if source else None
    for entry in _entries(request):
        if _LEVELS.get(entry["level"], 0) < min_level:
            continue
        if src:
            # 同时匹配来源（文件:行号）与模块名，子串、大小写不敏感
            origin = f"{entry['source'] or ''} {entry['name']}".lower()
            if src not in origin:
                continue
        ts = _parse_ts(entry["time"])
        if start_dt is not None and ts < start_dt:
            continue
        if end_dt is not None and ts > end_dt:
            continue
        yield entry


@router.get("/sources")
async def log_sources(request: Request) -> dict:
    """日志中出现过的来源（文件名或模块名，去重排序），供前端筛选下拉。"""
    sources: set[str] = set()
    for entry in _entries(request):
        origin = entry["source"] or entry["name"]
        # source 形如 scheduler.py:72，取文件名部分
        sources.add(origin.split(":", 1)[0])
    return {"sources": sorted(sources)}


@router.get("")
async def list_logs(
    request: Request,
    level: str | None = Query(default=None, description="最低级别：DEBUG/INFO/WARN/ERROR"),
    start: str | None = Query(
        default=None, description="起始时间 YYYY-MM-DD 或 YYYY-MM-DDTHH:MM:SS（本地时间）"
    ),
    end: str | None = Query(default=None, description="结束时间，格式同上"),
    source: str | None = Query(
        default=None,
        description="来源筛选：文件名（如 scheduler.py）或模块名（如 app.scheduler），子串匹配",
    ),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=1, le=500),
) -> dict:
    items = list(_filtered(request, level, start, end, source))
    items.reverse()  # 最新在前
    total = len(items)
    start_idx = (page - 1) * page_size
    return {
        "results": items[start_idx : start_idx + page_size],
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": (total + page_size - 1) // page_size if total else 0,
    }


@router.get("/export")
async def export_logs(
    request: Request,
    level: str | None = Query(default=None, description="最低级别：DEBUG/INFO/WARN/ERROR"),
    start: str | None = Query(default=None, description="起始时间，格式同列表接口"),
    end: str | None = Query(default=None, description="结束时间，格式同列表接口"),
    source: str | None = Query(default=None, description="来源筛选，格式同列表接口"),
) -> PlainTextResponse:
    lines = []
    for entry in _filtered(request, level, start, end, source):
        # 新格式含来源段；旧格式行无来源信息时按旧格式导出
        if entry["source"]:
            lines.append(
                f"{entry['time']} | {entry['level']} | {entry['name']}"
                f" | {entry['source']} | {entry['message']}"
            )
        else:
            lines.append(
                f"{entry['time']} | {entry['level']} | {entry['name']} | {entry['message']}"
            )
    text = "\n".join(lines) + ("\n" if lines else "")
    fname = f"logs-{datetime.now().strftime('%Y%m%d-%H%M%S')}.log"
    return PlainTextResponse(
        text, headers={"Content-Disposition": f'attachment; filename="{fname}"'}
    )
