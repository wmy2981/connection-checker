"""领域模型：检查目标、检查结果、过滤参数、状态统计。"""
from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator

CheckMethod = Literal["ping", "port", "http", "dns"]
Status = Literal["success", "fail", "timeout", "error"]
StatusOrAll = Literal["success", "fail", "timeout", "error", "all"]


def new_id() -> str:
    return uuid4().hex[:12]


class TimeRange(BaseModel):
    """时间段。start > end 表示跨午夜，如 22:00-06:00。"""

    start: str = "00:00"
    end: str = "23:59"

    @field_validator("start", "end")
    @classmethod
    def _validate_hhmm(cls, v: str) -> str:
        try:
            h, m = v.split(":")
            if not (0 <= int(h) <= 23 and 0 <= int(m) <= 59):
                raise ValueError
        except ValueError:
            raise ValueError(f"无效的时间格式 {v!r}，应为 HH:MM") from None
        return v


class TargetBase(BaseModel):
    name: str | None = Field(default=None, max_length=100)
    ip: str = Field(min_length=1, max_length=255)
    check_method: CheckMethod
    check_interval: int = Field(default=60, ge=0)  # 秒；0 = 关闭定时检查（仅手动）
    time_ranges: list[TimeRange] = Field(
        default_factory=lambda: [TimeRange(start="00:00", end="23:59")]
    )
    enabled: bool = True
    notify_enabled: bool = True  # 关闭后该目标不推送告警/恢复通知
    # port 检查
    port: int | None = Field(default=None, ge=1, le=65535)
    # ping 检查
    ping_count: int | None = Field(default=None, ge=1, le=20)  # None = 用全局默认
    # http 检查
    scheme: Literal["http", "https"] = "http"
    url_path: str = Field(default="/", max_length=500)
    http_success_codes: list[int] | None = None
    # 覆盖默认超时（秒）
    timeout: float | None = Field(default=None, gt=0)

    @field_validator("ip")
    @classmethod
    def _strip_ip(cls, v: str) -> str:
        return v.strip()


class TargetCreate(TargetBase):
    pass


class TargetUpdate(BaseModel):
    name: str | None = None
    ip: str | None = Field(default=None, min_length=1, max_length=255)
    check_method: CheckMethod | None = None
    check_interval: int | None = Field(default=None, ge=0)
    time_ranges: list[TimeRange] | None = None
    enabled: bool | None = None
    notify_enabled: bool | None = None
    ping_count: int | None = Field(default=None, ge=1, le=20)
    port: int | None = Field(default=None, ge=1, le=65535)
    scheme: Literal["http", "https"] | None = None
    url_path: str | None = Field(default=None, max_length=500)
    http_success_codes: list[int] | None = None
    timeout: float | None = Field(default=None, gt=0)


class Target(TargetBase):
    id: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class CheckResult(BaseModel):
    id: str = Field(default_factory=new_id)
    target_id: str
    target_name: str | None = None
    ip: str
    check_method: CheckMethod
    status: Status
    latency_ms: float | None = None
    message: str = ""
    extra: dict[str, Any] = Field(default_factory=dict)
    checked_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ResultFilter(BaseModel):
    status: str | None = None  # 逗号分隔多值（success,fail），空或 all 表示不筛
    ip: str | None = None
    target_name: str | None = None
    target_id: str | None = None
    date: str | None = None  # YYYY-MM-DD
    time_start: str | None = None
    time_end: str | None = None
    # 完整时间范围（本地时间 ISO，如 2026-08-09T22:00:00），支持跨日筛选
    start_at: str | None = None
    end_at: str | None = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=200)


class Paginated(BaseModel):
    results: list[CheckResult]
    total: int
    page: int
    page_size: int
    pages: int


class StatsSummary(BaseModel):
    total_targets: int
    enabled_targets: int
    last_total_checks: int
    last_success: int
    last_fail: int
    last_timeout: int
    last_error: int
    stats_window: int  # 上述计数统计的近 N 次检查窗口
    latest_check_at: datetime | None = None
    # 每个目标的最新状态
    target_status: list[dict[str, Any]]


class LoginRequest(BaseModel):
    access_code: str = Field(min_length=1, max_length=128)


class RunRequest(BaseModel):
    target_id: str | None = None


class WebhookConfig(BaseModel):
    """Webhook 告警配置，存于 config.json（非环境变量）。"""

    enabled: bool = True
    url: str | None = Field(default=None, max_length=500)
    fail_threshold: int = Field(default=3, ge=1, le=100)  # 连续失败次数


class S3Config(BaseModel):
    """S3 兼容存储配置，存于 config.json 的 s3 节；凭据（access id/key）存 secrets.json。"""

    enabled: bool = False
    endpoint: str = Field(default="", max_length=500)  # S3 服务地址，如 https://s3.example.com
    bucket: str = Field(default="", max_length=255)
    region: str | None = Field(default=None, max_length=100)  # 可选，部分 S3 服务要求
    datapath: str = Field(default="", max_length=500)  # 数据在 bucket 中的路径前缀


class AppSettings(BaseModel):
    """全局检查参数，存于 config.json 的 app 节（非环境变量，前端可配置）。"""

    result_max_records: int = Field(default=50000, ge=100, le=1_000_000)
    ping_count: int = Field(default=4, ge=1, le=20)
    connect_timeout: float = Field(default=3.0, gt=0, le=60)  # ping/TCP 超时（秒）
    http_timeout: float = Field(default=5.0, gt=0, le=120)  # HTTP 超时（秒）
    stats_window: int = Field(default=50, ge=10, le=10_000)  # 仪表盘统计的近 N 次检查
    log_level: str = Field(default="INFO", pattern="^(DEBUG|INFO|WARN|ERROR)$")
