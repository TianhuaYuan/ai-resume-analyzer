import asyncio
import logging
from collections.abc import Callable
from typing import Any, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")

# 不可重试的编程错误（重试也无法修复，应立即暴露）
NON_RETRYABLE = (
    TypeError,
    ValueError,
    AttributeError,
    KeyError,
    IndexError,
    AssertionError,
)


class RetryBudget:
    """重试预算：将最大次数 / 退避基数 / 可选超时收敛为可复用对象。

    取代原先散落的默认参数（max_retries=3, base_delay=1.0），
    便于统一调参与观测单次调用的重试次数。
    """

    def __init__(
        self,
        max_retries: int = 3,
        base_delay: float = 1.0,
        timeout: float | None = None,
    ) -> None:
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.timeout = timeout  # 单次调用超时（秒），None 表示不限制
        self.attempts = 0

    def delay_for(self, attempt: int) -> float:
        return self.base_delay * (2 ** attempt)

    def remaining(self) -> int:
        return max(0, self.max_retries - self.attempts)


async def with_retry(
    fn: Callable[..., Any],
    *args,
    max_retries: int = 3,
    base_delay: float = 1.0,
    fallback: T | None = None,
    budget: RetryBudget | None = None,
    **kwargs: Any,
) -> T:
    """指数退避重试：1s → 2s → 4s。

    - 支持同步 callable（如 ``parse_resume``）与异步 callable（如 ``llm_generate``）：
      同步函数直接调用，不再 ``await`` 其返回值（修复 C3 的 TypeError）。
    - 编程错误（TypeError/ValueError/...）直接抛出，不重试。
    - 传入 ``budget`` 时由其统一管理次数与退避基数。
    """
    if budget is not None:
        max_retries = budget.max_retries
        base_delay = budget.base_delay

    last_error: Exception | None = None
    for attempt in range(max_retries + 1):
        if budget is not None:
            budget.attempts = attempt
        try:
            if asyncio.iscoroutinefunction(fn):
                return await fn(*args, **kwargs)
            return fn(*args, **kwargs)  # 同步 callable：直接调用
        except NON_RETRYABLE:
            raise  # 编程错误不重试，直接抛
        except Exception as e:
            last_error = e
            if attempt < max_retries:
                delay = base_delay * (2 ** attempt)
                logger.warning(
                    "retry %d/%d after %.1fs: %s", attempt + 1, max_retries, delay, e
                )
                await asyncio.sleep(delay)
            else:
                logger.error("all %d retries exhausted: %s", max_retries, e)

    if fallback is not None:
        return fallback
    raise last_error  # type: ignore[misc]
