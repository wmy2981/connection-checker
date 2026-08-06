"""应用设置：由环境变量（前缀 CONNECTCHECKER_）与 .env 提供。"""
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_host: str = "0.0.0.0"
    app_port: int = 8000

    data_dir: Path = Path("data")

    # 认证
    access_code: str = ""  # 为空则首次启动随机生成并写入日志
    jwt_secret: str = ""  # 为空则首次启动随机生成并持久化
    jwt_expire_minutes: int = 720

    # 结果保留
    result_max_records: int = 50000

    # 告警通知
    notify_fail_threshold: int = 3  # 连续失败达到该次数触发 Webhook
    webhook_url: str | None = None  # 支持 Gotify / 企业微信 / 自建（POST JSON）

    # 检查参数默认值
    ping_count: int = 4
    connect_timeout: float = 3.0  # ping/TCP 超时（秒）
    http_timeout: float = 5.0  # HTTP 超时（秒）
    http_success_codes: list[int] = [
        200, 201, 202, 203, 204, 205, 206,
        300, 301, 302, 303, 304, 307, 308,
    ]

    # Cookie 仅在 HTTPS 下标记 Secure；本地 HTTP 调试需关闭
    cookie_secure: bool = False

    model_config = SettingsConfigDict(
        env_prefix="CONNECTCHECKER_",
        env_file=".env",
        extra="ignore",
    )

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)


settings = Settings()
