"""日志查看与导出：按时间范围、级别与来源过滤每日日志文件。

日志行格式（见 app/logging_setup.py）：
    2026-08-10 10:30:36,123 | INFO | app.scheduler | scheduler.py:72 | 消息文本
旧版格式无来源段（... | app.scheduler | 消息文本），解析时兼容。
traceback 等续行（不以时间戳开头）并入上一条的 message。
"""
import re
import time
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

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


def _entries(
    request: Request, start_dt: datetime | None = None, end_dt: datetime | None = None
):
    """按时间正序产出日志条目；续行并入上一条的 message。

    start_dt / end_dt 按文件名日期跳过范围外的日志文件（天级粗过滤，
    行级过滤仍精确），避免每次查询都解析全部历史文件。
    source 为产生日志的「文件名:行号」（如 scheduler.py:72）；旧格式行无来源
    信息时为 None（保留 name 供按模块筛选）。
    """
    last: dict | None = None
    for f in sorted(_log_dir(request).glob("app-*.log")):
        try:
            fdate = datetime.strptime(f.stem.removeprefix("app-"), "%Y-%m-%d")
        except ValueError:
            fdate = None
        if fdate is not None:
            if start_dt is not None and fdate < start_dt.replace(
                hour=0, minute=0, second=0, microsecond=0
            ):
                continue
            if end_dt is not None and fdate > end_dt.replace(
                hour=0, minute=0, second=0, microsecond=0
            ):
                continue
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
    # level / source 支持逗号分隔多值（前端多选）：级别精确集合，来源 OR 子串匹配
    # 文件里级别为标准名（WARNING），前端选项用短写 WARN，归一后再比较
    def _norm_level(v: str) -> str:
        return "WARNING" if v == "WARN" else v

    levels = (
        {_norm_level(s.upper()) for s in (level or "").split(",") if s.strip()}
        if level
        else None
    )
    srcs = [s.strip().lower() for s in source.split(",") if s.strip()] if source else None
    try:
        start_dt = _normalize_ts(start) if start else None
        end_dt = _normalize_ts(end) if end else None
    except ValueError as e:
        raise HTTPException(status_code=422, detail=f"无效的时间格式: {e}") from None
    for entry in _entries(request, start_dt, end_dt):
        if levels and _norm_level(entry["level"].upper()) not in levels:
            continue
        if srcs:
            # 同时匹配来源（文件:行号）与模块名，子串、大小写不敏感
            origin = f"{entry['source'] or ''} {entry['name']}".lower()
            if not any(s in origin for s in srcs):
                continue
        ts = _parse_ts(entry["time"])
        if start_dt is not None and ts < start_dt:
            continue
        if end_dt is not None and ts > end_dt:
            continue
        yield entry


# 来源枚举 TTL 缓存：避免每次打开日志弹窗都全量解析历史文件（来源变化不频繁）。
# 按日志目录分键，防止不同数据目录（测试实例、多实例）之间互相串扰。
_source_cache: dict[str, tuple[float, list[str]]] = {}
SOURCE_CACHE_TTL = 30.0


@router.get("/sources")
async def log_sources(request: Request) -> dict:
    """日志中出现过的来源（文件名或模块名，去重排序），供前端筛选下拉。"""
    key = str(request.app.state.settings.data_dir / "logs")
    now = time.monotonic()
    hit = _source_cache.get(key)
    if hit is not None and now - hit[0] < SOURCE_CACHE_TTL:
        return {"sources": hit[1]}
    sources: set[str] = set()
    for entry in _entries(request):
        origin = entry["source"] or entry["name"]
        # source 形如 scheduler.py:72，取文件名部分
        sources.add(origin.split(":", 1)[0])
    result = sorted(sources)
    _source_cache[key] = (now, result)
    return {"sources": result}


@router.get("")
async def list_logs(
    request: Request,
    level: str | None = Query(
        default=None, description="级别筛选，逗号分隔多值（如 DEBUG,WARN），精确匹配"
    ),
    start: str | None = Query(
        default=None, description="起始时间 YYYY-MM-DD 或 YYYY-MM-DDTHH:MM:SS（本地时间）"
    ),
    end: str | None = Query(default=None, description="结束时间，格式同上"),
    source: str | None = Query(
        default=None,
        description="来源筛选，逗号分隔多值（OR）：文件名或模块名，子串匹配",
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
    level: str | None = Query(default=None, description="级别筛选，逗号分隔多值，格式同列表接口"),
    start: str | None = Query(default=None, description="起始时间，格式同列表接口"),
    end: str | None = Query(default=None, description="结束时间，格式同列表接口"),
    source: str | None = Query(default=None, description="来源筛选，逗号分隔多值，格式同列表接口"),
) -> StreamingResponse:
    def _gen():
        for entry in _filtered(request, level, start, end, source):
            # 新格式含来源段；旧格式行无来源信息时按旧格式导出
            if entry["source"]:
                yield (
                    f"{entry['time']} | {entry['level']} | {entry['name']}"
                    f" | {entry['source']} | {entry['message']}\n"
                )
            else:
                yield (
                    f"{entry['time']} | {entry['level']} | {entry['name']}"
                    f" | {entry['message']}\n"
                )

    fname = f"logs-{datetime.now().strftime('%Y%m%d-%H%M%S')}.log"
    return StreamingResponse(
        _gen(),
        media_type="text/plain",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )
