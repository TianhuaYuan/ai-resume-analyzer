"""with_retry 可靠性增强版（P0.7）。

三项改动：
1. Full Jitter + 封顶 — delay_for 在 [0, base*2^attempt] 区间均匀随机，被 max_cap 封顶
2. classify_error 七分类 — 不同分类采取不同重试策略：
   - RATE_LIMIT：翻倍退避 + 多重试（5 次）
   - TIMEOUT：缩短退避 + 少重试（1 次）
   - NON_RETRYABLE/AUTH/NOT_FOUND：立即抛出
   - NETWORK/UNKNOWN：正常重试（默认 max_retries）
3. timeout 落实 — budget.timeout 通过 wait_for 应用到每次 fn 调用

附带修复：改用 inspect 模块判断协程函数（旧 API 在 Python 3.16 弃用）
"""

import asyncio
import inspect
import logging
import random
from collections.abc import Callable
from typing import Any, TypeVar

from core.error_types import ErrorCategory, classify_error

logger = logging.getLogger(__name__)

T = TypeVar("T")

# 单次退避默认封顶（即使指数增长也不会超过 60s）
DEFAULT_MAX_CAP = 60.0

# 各分类的默认重试次数上限（即使 max_retries=10，TIMEOUT 也只重试 1 次）
_CATEGORY_MAX_RETRIES: dict[ErrorCategory, int] = {
    ErrorCategory.RATE_LIMIT: 5,    # 限流：多重试（短时间内可能恢复）
    ErrorCategory.TIMEOUT: 1,        # 超时：少重试（可能下游死锁）
    ErrorCategory.NETWORK: 3,        # 网络：正常重试
    ErrorCategory.UNKNOWN: 3,         # 未知：正常重试
    ErrorCategory.NON_RETRYABLE: 0,  # 编程错误：不重试
    ErrorCategory.AUTH: 0,           # 认证失败：不重试
    ErrorCategory.NOT_FOUND: 0,      # 资源不存在：不重试
}

# 各分类的退避乘数（对 base_delay 的缩放）
_CATEGORY_BACKOFF_MULTIPLIER: dict[ErrorCategory, float] = {
    ErrorCategory.RATE_LIMIT: 2.0,   # 翻倍退避
    ErrorCategory.TIMEOUT: 0.5,       # 缩短退避
    ErrorCategory.NETWORK: 1.0,       # 正常退避
    ErrorCategory.UNKNOWN: 1.0,       # 正常退避
}


class RetryBudget:
    """重试预算：将最大次数 / 退避基数 / 超时 / 退避封顶收敛为可复用对象。

    取代原先散落的默认参数（max_retries=3, base_delay=1.0），
    便于统一调参与观测单次调用的重试次数。

    P0.7 增强：
    - max_cap: 单次退避上限（默认 60s），防止指数爆炸
    - timeout: 单次 fn 调用超时（秒），通过 asyncio.wait_for 落实
    """

    def __init__(
        self,
        max_retries: int = 3,
        base_delay: float = 1.0,
        timeout: float | None = None,
        max_cap: float = DEFAULT_MAX_CAP,
    ) -> None:
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.timeout = timeout  # 单次调用超时（秒），None 表示不限制
        self.max_cap = max_cap  # 单次退避时间上限（秒）
        self.attempts = 0

    def delay_for(self, attempt: int) -> float:
        """Full Jitter：在 [0, base*2^attempt] 区间均匀随机，并被 max_cap 封顶。

        Full Jitter 比传统指数退避更优：
        - 多协程同时失败时不会共振重试（随机性打散）
        - 退避时间随次数增长但被 max_cap 封顶，避免退避失控
        """
        upper = min(self.base_delay * (2 ** attempt), self.max_cap)
        return random.uniform(0, upper)

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
    """指数退避重试（Full Jitter + 错误分类 + timeout 落实）。

    - 支持同步 callable（如 ``parse_resume``）与异步 callable（如 ``llm_generate``）：
      同步函数直接调用，不再 ``await`` 其返回值。
    - 编程错误（TypeError/ValueError/...）/认证失败/资源不存在直接抛出，不重试。
    - 传入 ``budget`` 时由其统一管理次数与退避基数。
    - ``budget.timeout`` 通过 ``asyncio.wait_for`` 落实，单次 fn 调用永不永久挂起。
    - 错误分类策略：RATE_LIMIT 翻倍退避+多重试；TIMEOUT 缩短退避+少重试；
      NETWORK/UNKNOWN 正常重试。

    Args:
        fn: 要调用的函数（同步或异步）
        *args: 传给 fn 的位置参数
        max_retries: 最大重试次数（默认 3）
        base_delay: 退避基数（默认 1.0 秒）
        fallback: 重试耗尽后返回的兜底值（None 表示抛异常）
        budget: 可选的 RetryBudget，提供 max_retries/base_delay/timeout/max_cap
        **kwargs: 传给 fn 的关键字参数

    Returns:
        fn 的返回值，或 fallback（如果重试耗尽且传了 fallback）
    """
    if budget is not None:
        max_retries = budget.max_retries
        base_delay = budget.base_delay

    last_error: Exception | None = None
    is_async_fn = inspect.iscoroutinefunction(fn)

    for attempt in range(max_retries + 1):
        if budget is not None:
            budget.attempts = attempt
        try:
            if is_async_fn:
                # 异步 callable：可选套 asyncio.wait_for 落实 timeout
                if budget is not None and budget.timeout is not None:
                    return await asyncio.wait_for(
                        fn(*args, **kwargs), timeout=budget.timeout
                    )
                return await fn(*args, **kwargs)
            # 同步 callable：直接调用
            return fn(*args, **kwargs)
        except Exception as e:
            last_error = e
            category = classify_error(e)

            # NON_RETRYABLE/AUTH/NOT_FOUND 立即停止重试循环
            # （不重试，但如果传了 fallback 仍走 fallback 逻辑，保持调用方降级语义）
            if category in (
                ErrorCategory.NON_RETRYABLE,
                ErrorCategory.AUTH,
                ErrorCategory.NOT_FOUND,
            ):
                logger.warning(
                    "category=%s not retryable, stopping (attempt=%d): %s",
                    category.value, attempt, e,
                )
                break

            # 该分类的最大重试次数（取 min(配置的 max_retries, 分类策略))
            cat_max = _CATEGORY_MAX_RETRIES.get(category, max_retries)
            if attempt >= cat_max:
                logger.error(
                    "category=%s retries exhausted (attempt=%d): %s",
                    category.value, attempt, e,
                )
                break

            # 计算退避：Full Jitter + 分类特定乘数
            if budget is not None:
                raw_delay = budget.delay_for(attempt)
            else:
                # 不用 budget 时也要 Full Jitter（保持一致性）
                upper = min(base_delay * (2 ** attempt), DEFAULT_MAX_CAP)
                raw_delay = random.uniform(0, upper)
            multiplier = _CATEGORY_BACKOFF_MULTIPLIER.get(category, 1.0)
            delay = min(raw_delay * multiplier, DEFAULT_MAX_CAP)

            logger.warning(
                "retry %d/%d (cat=%s) after %.2fs: %s",
                attempt + 1, max_retries, category.value, delay, e,
            )
            await asyncio.sleep(delay)

    if fallback is not None:
        return fallback
    raise last_error  # type: ignore[misc]
