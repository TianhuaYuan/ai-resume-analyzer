import asyncio
import logging
from collections.abc import Callable, Coroutine
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

async def with_retry(
    fn: Callable[..., Coroutine[Any, Any, T]],
    *args,
    max_retries: int = 3,
    base_delay: float = 1.0,
    fallback: T | None = None,
    **kwargs,
) -> T:
    """指数退避重试：1s → 2s → 4s。
    所有异常默认重试，但编程错误（TypeError/ValueError/KeyError 等）直接抛出。"""
    last_error: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            return await fn(*args, **kwargs)
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