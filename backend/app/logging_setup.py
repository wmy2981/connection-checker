"""日志装配：控制台 + 每日文件（按本地时区 app-YYYY-MM-DD.log），级别可热更新。

级别来源为 config.json 的 app.log_level（DEBUG/INFO/WARN/ERROR），由启动时装配、
watchdog 检测到配置变更时热更新。文件按进程本地时区（容器内 TZ 环境变量生效）
每天切一个新文件。旧日志的清理（删除或上传 S3）由 LogCleaner 服务按
config.json 的 app.log_cleanup_mode / app.log_retention_days 执行。
"""
import logging
import sys
from datetime import datetime
from pathlib import Path

_LEVELS = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARN": logging.WARNING,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
}

# filename:lineno 精确到产生日志的 Python 文件与行号，供日志按来源筛选
_FORMAT = "%(asctime)s | %(levelname)s | %(name)s | %(filename)s:%(lineno)d | %(message)s"


def parse_level(level: str) -> int:
    """把配置字符串（DEBUG/INFO/WARN/ERROR，忽略大小写）转成 logging 级别。"""
    return _LEVELS.get(level.strip().upper(), logging.INFO)


class DailyFileHandler(logging.Handler):
    """按本地日期（datetime.now().astimezone()）切换文件的处理器。

    TimedRotatingFileHandler 的轮转基于进程本地时间，Windows 开发机上不读 TZ
    环境变量；这里显式用 astimezone() 保证与前端展示时区一致。文件名为
    app-YYYY-MM-DD.log；旧文件清理由 LogCleaner 服务负责。
    """

    def __init__(self, log_dir: Path, encoding: str = "utf-8") -> None:
        super().__init__()
        self.log_dir = Path(log_dir)
        self.encoding = encoding
        self._current_date: str | None = None
        self._stream = None
        self.setFormatter(logging.Formatter(_FORMAT))

    def emit(self, record: logging.LogRecord) -> None:
        try:
            date = datetime.now().astimezone().strftime("%Y-%m-%d")
            if date != self._current_date:
                self._roll(date)
            self._stream.write(self.format(record) + "\n")
            self._stream.flush()
        except Exception:  # noqa: BLE001
            self.handleError(record)

    def _roll(self, date: str) -> None:
        if self._stream is not None:
            self._stream.close()
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self._stream = open(
            self.log_dir / f"app-{date}.log", "a", encoding=self.encoding
        )
        self._current_date = date

    def close(self) -> None:
        if self._stream is not None:
            self._stream.close()
            self._stream = None
        super().close()


def configure(log_dir: Path, level: str = "INFO") -> None:
    """装配根 logger：控制台 + 每日文件；uvicorn 系列统一交给根 logger。"""
    root = logging.getLogger()
    lvl = parse_level(level)
    root.setLevel(lvl)
    for handler in list(root.handlers):
        root.removeHandler(handler)
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(logging.Formatter(_FORMAT))
    root.addHandler(console)
    root.addHandler(DailyFileHandler(log_dir))
    # uvicorn 自带 handler 只输出控制台且格式简单；统一交给根 logger（进文件）
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        lg = logging.getLogger(name)
        lg.handlers.clear()
        lg.propagate = True
        lg.setLevel(lvl)


def apply_level(level: str) -> None:
    """热更新日志级别（config.json 的 app.log_level 变更后调用）。"""
    lvl = parse_level(level)
    logging.getLogger().setLevel(lvl)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logging.getLogger(name).setLevel(lvl)
