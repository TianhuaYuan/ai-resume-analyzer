"""with_retry 可靠性增强测试（P0.7）。

TDD RED：以下三项改动尚未实现，所有用例应失败：
1. Full Jitter + 封顶：delay_for 返回 [0, base*2^attempt] 随机值，被 max_cap 封顶
2. classify_error 七分类：RATE_LIMIT/timeout/NETWORK 等不同策略
3. timeout 落实：budget.timeout 通过 asyncio.wait_for 生效
4. 附带：asyncio.iscoroutinefunction → inspect.iscoroutinefunction

GREEN 阶段实现后所有用例通过。
"""

from __future__ import annotations

import asyncio
import inspect
from unittest.mock import AsyncMock, patch

import pytest

from core.error_types import ErrorCategory, classify_error
from core.retry import RetryBudget, with_retry


# ── 1. Full Jitter + 封顶 ──────────────────────────────────────────


class TestFullJitter:
    """delay_for 改用 Full Jitter：在 [0, base*2^attempt] 区间均匀随机。"""

    def test_delay_for_returns_value_within_jitter_range(self):
        """delay_for(attempt) 应 ∈ [0, base * 2^attempt]。"""
        budget = RetryBudget(base_delay=1.0)
        for attempt in range(5):
            delay = budget.delay_for(attempt)
            upper = 1.0 * (2 ** attempt)
            assert 0 <= delay <= upper, f"attempt={attempt} delay={delay} upper={upper}"

    def test_delay_for_caps_at_max_cap(self):
        """delay_for 应被 max_cap 封顶（避免高 attempt 值导致天文数字 sleep）。"""
        budget = RetryBudget(base_delay=10.0, max_cap=30.0)
        # attempt=5 → 10*2^5=320，应被 cap 在 30
        for _ in range(20):
            assert budget.delay_for(5) <= 30.0

    def test_delay_for_is_random(self):
        """Full Jitter 应产生随机值，多次调用应有差异。"""
        budget = RetryBudget(base_delay=1.0)
        values = {budget.delay_for(3) for _ in range(20)}
        # 极小概率全部相同；实际应至少有 2 个不同值
        assert len(values) > 1, "Full Jitter 应产生随机性"

    def test_delay_for_zero_at_attempt_zero(self):
        """attempt=0 → base*2^0=base，区间 [0, base]。"""
        budget = RetryBudget(base_delay=2.0)
        for _ in range(10):
            delay = budget.delay_for(0)
            assert 0 <= delay <= 2.0

    def test_retry_budget_accepts_max_cap_parameter(self):
        """RetryBudget 应接受 max_cap 参数。"""
        budget = RetryBudget(max_cap=15.0)
        assert budget.max_cap == 15.0

    def test_retry_budget_default_max_cap(self):
        """未传 max_cap 时应有合理默认值（避免退避时间失控）。"""
        budget = RetryBudget()
        assert budget.max_cap > 0
        assert budget.max_cap <= 300  # 不超过 5 分钟


# ── 2. classify_error 七分类 ──────────────────────────────────────────


class TestClassifyError:
    """classify_error 应将异常映射到 7 类之一。"""

    def test_classify_non_retryable_type_error(self):
        """TypeError → NON_RETRYABLE。"""
        assert classify_error(TypeError("bad")) == ErrorCategory.NON_RETRYABLE

    def test_classify_non_retryable_value_error(self):
        """ValueError → NON_RETRYABLE。"""
        assert classify_error(ValueError("bad")) == ErrorCategory.NON_RETRYABLE

    def test_classify_non_retryable_attribute_error(self):
        """AttributeError → NON_RETRYABLE。"""
        assert classify_error(AttributeError("bad")) == ErrorCategory.NON_RETRYABLE

    def test_classify_non_retryable_key_error(self):
        """KeyError → NON_RETRYABLE。"""
        assert classify_error(KeyError("bad")) == ErrorCategory.NON_RETRYABLE

    def test_classify_timeout(self):
        """asyncio.TimeoutError → TIMEOUT。"""
        assert classify_error(asyncio.TimeoutError()) == ErrorCategory.TIMEOUT

    def test_classify_builtin_timeout(self):
        """内置 TimeoutError → TIMEOUT（Python 3.11+ asyncio.TimeoutError 是别名）。"""
        assert classify_error(TimeoutError()) == ErrorCategory.TIMEOUT

    def test_classify_network(self):
        """httpx.ConnectError → NETWORK。"""
        import httpx
        err = httpx.ConnectError("conn refused")
        assert classify_error(err) == ErrorCategory.NETWORK

    def test_classify_network_read_error(self):
        """httpx.ReadError → NETWORK。"""
        import httpx
        err = httpx.ReadError("read failed")
        assert classify_error(err) == ErrorCategory.NETWORK

    def test_classify_unknown_for_generic_exception(self):
        """未识别的 Exception → UNKNOWN。"""
        assert classify_error(Exception("unknown")) == ErrorCategory.UNKNOWN

    def test_classify_rate_limit_openai(self):
        """openai.RateLimitError → RATE_LIMIT。"""
        try:
            from openai import RateLimitError
        except ImportError:
            pytest.skip("openai not installed")
        # openai v1+ 的 RateLimitError 构造需要 response/body 对象，
        # 直接构造会失败。这里只验证 isinstance 路径存在。
        # 用最小 mock 创建一个伪造实例绕过构造：
        import httpx
        try:
            request = httpx.Request(method="POST", url="http://x")
            response = httpx.Response(status_code=429, request=request)
            err = RateLimitError(
                message="rate limit",
                response=response,
                body=None,
            )
        except (TypeError, Exception):
            # 不同 openai 版本构造签名不同，跳过该测试
            pytest.skip("RateLimitError constructor incompatible")
        assert classify_error(err) == ErrorCategory.RATE_LIMIT


# ── 3. with_retry 错误分类策略 ──────────────────────────────────────────


class TestWithRetryClassification:
    """with_retry 应根据分类采取不同策略。"""

    @pytest.mark.asyncio
    async def test_non_retryable_raises_immediately(self):
        """TypeError 应立即抛出，不重试。"""
        call_count = 0

        async def failing_fn():
            nonlocal call_count
            call_count += 1
            raise TypeError("bad type")

        with pytest.raises(TypeError):
            await with_retry(failing_fn, max_retries=3, base_delay=0.01)
        assert call_count == 1, "NON_RETRYABLE 应立即抛出不重试"

    @pytest.mark.asyncio
    async def test_network_error_retries(self):
        """NETWORK 错误应正常重试 max_retries 次后抛出。"""
        import httpx
        call_count = 0

        async def failing_fn():
            nonlocal call_count
            call_count += 1
            raise httpx.ConnectError("conn refused")

        with patch("core.retry.asyncio.sleep", new=AsyncMock()):
            with pytest.raises(httpx.ConnectError):
                await with_retry(failing_fn, max_retries=2, base_delay=0.01)
        assert call_count == 3  # 1 初次 + 2 重试

    @pytest.mark.asyncio
    async def test_timeout_error_retries_less(self):
        """TIMEOUT 错误应少重试（不达到 max_retries）。"""
        call_count = 0

        async def slow_fn():
            nonlocal call_count
            call_count += 1
            raise asyncio.TimeoutError()

        with patch("core.retry.asyncio.sleep", new=AsyncMock()):
            with pytest.raises(asyncio.TimeoutError):
                await with_retry(slow_fn, max_retries=5, base_delay=0.01)
        # TIMEOUT 默认只重试 1 次，总调用 2 次
        assert call_count <= 3, f"TIMEOUT 应少重试，实际调用 {call_count} 次"

    @pytest.mark.asyncio
    async def test_unknown_error_retries(self):
        """UNKNOWN 错误应正常重试。"""
        call_count = 0

        async def failing_fn():
            nonlocal call_count
            call_count += 1
            raise RuntimeError("unknown")

        with patch("core.retry.asyncio.sleep", new=AsyncMock()):
            with pytest.raises(RuntimeError):
                await with_retry(failing_fn, max_retries=2, base_delay=0.01)
        assert call_count == 3  # 1 + 2 重试

    @pytest.mark.asyncio
    async def test_fallback_swallows_after_exhausted(self):
        """重试耗尽后，传 fallback 应返回 fallback 而非抛出。"""
        import httpx

        async def failing_fn():
            raise httpx.ConnectError("conn refused")

        with patch("core.retry.asyncio.sleep", new=AsyncMock()):
            result = await with_retry(
                failing_fn,
                max_retries=1,
                base_delay=0.01,
                fallback="recovered",
            )
        assert result == "recovered"


# ── 4. timeout 落实 ──────────────────────────────────────────


class TestTimeoutEnforcement:
    """budget.timeout 应通过 asyncio.wait_for 落实。"""

    @pytest.mark.asyncio
    async def test_timeout_raises_when_fn_exceeds_budget(self):
        """单次 fn 调用超过 budget.timeout → asyncio.TimeoutError。"""
        async def slow_fn():
            await asyncio.sleep(10)
            return "done"

        budget = RetryBudget(timeout=0.1, max_retries=1, base_delay=0.01)
        with pytest.raises((asyncio.TimeoutError, TimeoutError)):
            await with_retry(slow_fn, budget=budget)

    @pytest.mark.asyncio
    async def test_timeout_not_applied_without_budget(self):
        """未传 budget 或 budget.timeout=None 时，不应套 asyncio.wait_for。"""
        async def fast_fn():
            return "ok"

        result = await with_retry(fast_fn)
        assert result == "ok"

    @pytest.mark.asyncio
    async def test_timeout_not_applied_with_budget_no_timeout(self):
        """传了 budget 但 timeout=None 时，不应套 asyncio.wait_for。"""
        async def fast_fn():
            return "ok"

        budget = RetryBudget(max_retries=1, base_delay=0.01, timeout=None)
        result = await with_retry(fast_fn, budget=budget)
        assert result == "ok"


# ── 5. inspect.iscoroutinefunction 替换 ──────────────────────────────────────────


class TestInspectReplacement:
    """with_retry 应使用 inspect.iscoroutinefunction 而非 asyncio.iscoroutinefunction。"""

    def test_source_uses_inspect_not_asyncio(self):
        """core.retry 源码中应使用 inspect.iscoroutinefunction。"""
        import core.retry
        source = inspect.getsource(core.retry)
        assert "inspect.iscoroutinefunction" in source, "应使用 inspect.iscoroutinefunction"
        assert "asyncio.iscoroutinefunction" not in source, "不应再使用 asyncio.iscoroutinefunction"

    @pytest.mark.asyncio
    async def test_sync_function_still_works(self):
        """同步 callable 仍能正常调用（不 await 返回值）。"""

        def sync_fn(x: int) -> int:
            return x * 2

        result = await with_retry(sync_fn, 5)
        assert result == 10

    @pytest.mark.asyncio
    async def test_async_function_still_works(self):
        """异步 callable 仍能正常调用。"""
        async def async_fn(x: int) -> int:
            await asyncio.sleep(0)
            return x * 3

        result = await with_retry(async_fn, 5)
        assert result == 15


# ── 6. 兼容性：原 fallback 行为不破 ──────────────────────────────────────────


class TestBackwardCompatibility:
    """改造后原有调用方应零回归。"""

    @pytest.mark.asyncio
    async def test_first_try_success(self):
        """首次成功直接返回，不重试。"""
        call_count = 0

        async def good_fn():
            nonlocal call_count
            call_count += 1
            return "ok"

        result = await with_retry(good_fn, max_retries=3, base_delay=0.01)
        assert result == "ok"
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_fallback_after_all_fail(self):
        """全部重试失败 + 传 fallback → 返回 fallback。"""
        async def always_fail():
            raise RuntimeError("fail")

        with patch("core.retry.asyncio.sleep", new=AsyncMock()):
            result = await with_retry(
                always_fail,
                max_retries=2,
                base_delay=0.01,
                fallback="fallback",
            )
        assert result == "fallback"

    @pytest.mark.asyncio
    async def test_raises_when_no_fallback(self):
        """全部失败 + 未传 fallback → 抛最后异常。"""
        async def always_fail():
            raise RuntimeError("fail")

        with patch("core.retry.asyncio.sleep", new=AsyncMock()):
            with pytest.raises(RuntimeError, match="fail"):
                await with_retry(always_fail, max_retries=1, base_delay=0.01)

    def test_retry_budget_remaining(self):
        """RetryBudget.remaining() 仍正常工作。"""
        budget = RetryBudget(max_retries=3)
        assert budget.remaining() == 3
        budget.attempts = 2
        assert budget.remaining() == 1
