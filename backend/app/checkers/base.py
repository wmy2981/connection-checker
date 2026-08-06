"""检查器抽象与结果对象。"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from app.models import Status, Target


@dataclass
class CheckOutcome:
    status: Status
    message: str
    latency_ms: float | None = None
    extra: dict[str, Any] = field(default_factory=dict)


class BaseChecker(ABC):
    """所有检查器的公共接口。实现需保持 async 且不阻塞事件循环。"""

    def __init__(self, timeout: float) -> None:
        self.timeout = timeout

    @abstractmethod
    async def check(self, target: Target) -> CheckOutcome:
        ...
