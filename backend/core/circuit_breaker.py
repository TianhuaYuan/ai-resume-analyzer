"""熔断器实现 — 三态：CLOSED / OPEN / HALF_OPEN。

按外部依赖实例化（如 Chat API、Embedding API 各自独立熔断器），
避免一个服务故障拖垮所有 LLM 调用。

设计原则：
- OPEN 时快速失败，不执行实际调用
- 客户端断连（CancelledError）不计入失败
- 半开状态只允许有限试探调用
"""

import asyncio
import logging
import time
from collections.abc import Callable
from typing import TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


class CircuitBreakerOpenError(Exception):
    """熔断器处于 OPEN 或 HALF_OPEN（配额已满）状态时抛出。"""


class CircuitBreaker:
    """异步熔断器。

    Args:
        name: 熔断器名称（用于日志）
        failure_threshold: 连续失败次数阈值，达到后进入 OPEN
        recovery_timeout: 从 OPEN 到 HALF_OPEN 的恢复等待时间（秒）
        half_open_max_calls: HALF_OPEN 状态下允许的试探调用次数
    """

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"

    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
        half_open_max_calls: int = 1,
    ) -> None:
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_max_calls = half_open_max_calls

        self.state = self.CLOSED
        self.failure_count = 0
        self.last_failure_time: float | None = None
        self._half_open_calls = 0
        self._lock = asyncio.Lock()

    async def call(self, fn: Callable[..., T], *args, **kwargs) -> T:
        """在熔断器保护下调用函数。

        成功时重置失败计数；失败时（除 CancelledError 外）增加计数；
        CancelledError 直接抛出，不计入失败。
        """
        await self.check()

        try:
            if asyncio.iscoroutinefunction(fn):
                result = await fn(*args, **kwargs)
            else:
                result = fn(*args, **kwargs)
            await self.report_success()
            return result
        except asyncio.CancelledError:
            raise
        except Exception:
            await self.report_failure()
            raise

    async def check(self) -> None:
        """检查熔断器状态，OPEN 时抛 CircuitBreakerOpenError。

        HALF_OPEN 时允许有限次调用，超过配额后抛异常。
        """
        async with self._lock:
            now = time.time()

            if self.state == self.OPEN:
                if self.last_failure_time and (now - self.last_failure_time) >= self.recovery_timeout:
                    self.state = self.HALF_OPEN
                    self._half_open_calls = 0
                    logger.info("Breaker %s: OPEN -> HALF_OPEN", self.name)
                else:
                    raise CircuitBreakerOpenError(
                        f"Circuit breaker '{self.name}' is OPEN"
                    )

            if self.state == self.HALF_OPEN:
                if self._half_open_calls >= self.half_open_max_calls:
                    raise CircuitBreakerOpenError(
                        f"Circuit breaker '{self.name}' is HALF_OPEN (max calls reached)"
                    )
                self._half_open_calls += 1

    async def report_success(self) -> None:
        """通知熔断器调用成功。"""
        async with self._lock:
            if self.state == self.HALF_OPEN:
                self.state = self.CLOSED
                self.failure_count = 0
                self._half_open_calls = 0
                logger.info("Breaker %s: HALF_OPEN -> CLOSED", self.name)
            elif self.state == self.CLOSED:
                self.failure_count = 0

    async def report_failure(self) -> None:
        """通知熔断器调用失败（CancelledError 不应调用此方法）。"""
        async with self._lock:
            self.failure_count += 1
            self.last_failure_time = time.time()

            if self.state == self.HALF_OPEN:
                self.state = self.OPEN
                logger.warning("Breaker %s: HALF_OPEN -> OPEN", self.name)
            elif self.state == self.CLOSED and self.failure_count >= self.failure_threshold:
                self.state = self.OPEN
                logger.warning(
                    "Breaker %s: CLOSED -> OPEN (failures=%d/%d)",
                    self.name, self.failure_count, self.failure_threshold,
                )
