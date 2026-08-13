"""熔断器三态 + 重试分类 —— OPEN 快速失败、半开试探、断连不计数。

测试范围：
- CircuitBreaker 三态转换
- with_retry 集成 breaker
- 5xx 错误分类（可重试）
- CancelledError 不计入熔断失败
"""

import asyncio

import pytest


# ═══════════════════════════════════════════════════════════
# RED: CircuitBreaker 三态核心
# ═══════════════════════════════════════════════════════════


class TestCircuitBreakerStates:
    """熔断器三态转换测试。"""

    @pytest.mark.asyncio
    async def test_closed_allows_calls(self):
        """CLOSED 状态允许调用通过。"""
        from core.circuit_breaker import CircuitBreaker

        cb = CircuitBreaker("test", failure_threshold=3, recovery_timeout=1)
        assert cb.state == "closed"

        # 模拟成功调用
        async def ok_fn():
            return "ok"

        result = await cb.call(ok_fn)
        assert result == "ok"

    @pytest.mark.asyncio
    async def test_opens_after_failures(self):
        """连续失败达到阈值后进入 OPEN。"""
        from core.circuit_breaker import CircuitBreaker

        cb = CircuitBreaker("test", failure_threshold=2, recovery_timeout=60)

        async def fail():
            raise RuntimeError("boom")

        with pytest.raises(RuntimeError):
            await cb.call(fail)
        assert cb.state == "closed"  # 第一次失败未达阈值

        with pytest.raises(RuntimeError):
            await cb.call(fail)
        assert cb.state == "open"  # 第二次失败，达到阈值

    @pytest.mark.asyncio
    async def test_open_fast_fails(self):
        """OPEN 状态直接抛 CircuitBreakerOpenError，不执行实际调用。"""
        from core.circuit_breaker import CircuitBreaker, CircuitBreakerOpenError

        cb = CircuitBreaker("test", failure_threshold=1, recovery_timeout=60)

        async def fail():
            raise RuntimeError("boom")

        with pytest.raises(RuntimeError):
            await cb.call(fail)
        assert cb.state == "open"

        with pytest.raises(CircuitBreakerOpenError):
            async def should_not_run():
                return "should_not_run"
            await cb.call(should_not_run)

    @pytest.mark.asyncio
    async def test_half_open_after_timeout(self):
        """OPEN 超过 recovery_timeout 后进入 HALF_OPEN。"""
        from core.circuit_breaker import CircuitBreaker

        cb = CircuitBreaker("test", failure_threshold=1, recovery_timeout=0.05)

        async def fail():
            raise RuntimeError("boom")

        with pytest.raises(RuntimeError):
            await cb.call(fail)
        assert cb.state == "open"

        # 等待恢复超时
        await asyncio.sleep(0.1)

        # 下一次调用进入半开
        async def ok():
            return "ok"

        result = await cb.call(ok)
        assert result == "ok"
        assert cb.state == "closed"  # 半开成功，关闭

    @pytest.mark.asyncio
    async def test_half_open_failure_reopens(self):
        """HALF_OPEN 失败一次后回到 OPEN。"""
        from core.circuit_breaker import CircuitBreaker

        cb = CircuitBreaker("test", failure_threshold=1, recovery_timeout=0.05)

        async def fail():
            raise RuntimeError("boom")

        with pytest.raises(RuntimeError):
            await cb.call(fail)
        assert cb.state == "open"

        await asyncio.sleep(0.1)

        # 半开状态下再次失败
        with pytest.raises(RuntimeError):
            await cb.call(fail)
        assert cb.state == "open"

    @pytest.mark.asyncio
    async def test_cancelled_error_not_counted(self):
        """CancelledError（客户端断连）不计入失败计数。"""
        from core.circuit_breaker import CircuitBreaker

        cb = CircuitBreaker("test", failure_threshold=2, recovery_timeout=60)

        async def cancelled():
            raise asyncio.CancelledError()

        with pytest.raises(asyncio.CancelledError):
            await cb.call(cancelled)

        assert cb.failure_count == 0
        assert cb.state == "closed"

    @pytest.mark.asyncio
    async def test_success_resets_failure_count(self):
        """成功后重置失败计数。"""
        from core.circuit_breaker import CircuitBreaker

        cb = CircuitBreaker("test", failure_threshold=3, recovery_timeout=60)

        async def fail():
            raise RuntimeError("boom")

        with pytest.raises(RuntimeError):
            await cb.call(fail)
        assert cb.failure_count == 1

        # 成功调用
        async def ok_fn():
            return "ok"

        result = await cb.call(ok_fn)
        assert result == "ok"
        assert cb.failure_count == 0


# ═══════════════════════════════════════════════════════════
# RED: with_retry 集成 breaker
# ═══════════════════════════════════════════════════════════


class TestWithRetryBreakerIntegration:
    """with_retry 集成 breaker 测试。"""

    @pytest.mark.asyncio
    async def test_breaker_open_skips_retry(self):
        """breaker OPEN 时 with_retry 直接抛 CircuitBreakerOpenError，不重试。"""
        from core.circuit_breaker import CircuitBreaker, CircuitBreakerOpenError
        from core.retry import with_retry

        cb = CircuitBreaker("test", failure_threshold=1, recovery_timeout=60)

        async def fail():
            raise RuntimeError("boom")

        # 先让熔断器 OPEN
        with pytest.raises(RuntimeError):
            await with_retry(fail, breaker=cb, max_retries=0)
        assert cb.state == "open"

        # 再次调用应直接抛 CircuitBreakerOpenError，不重试
        with pytest.raises(CircuitBreakerOpenError):
            await with_retry(fail, breaker=cb, max_retries=3)

    @pytest.mark.asyncio
    async def test_breaker_counts_retry_failures(self):
        """with_retry 多次失败时 breaker 正确计数（只计最终失败，不重试期间的每次失败）。"""
        from core.circuit_breaker import CircuitBreaker
        from core.retry import with_retry

        cb = CircuitBreaker("test", failure_threshold=2, recovery_timeout=60)

        async def fail():
            raise RuntimeError("boom")

        # 第一次调用：重试 1 次后最终失败，breaker 计 1 次
        with pytest.raises(RuntimeError):
            await with_retry(fail, breaker=cb, max_retries=1, base_delay=0.01)
        assert cb.failure_count == 1
        assert cb.state == "closed"

    @pytest.mark.asyncio
    async def test_breaker_success_on_retry(self):
        """with_retry 最终成功时 breaker 重置失败计数。"""
        from core.circuit_breaker import CircuitBreaker
        from core.retry import with_retry

        cb = CircuitBreaker("test", failure_threshold=3, recovery_timeout=60)

        attempts = 0

        async def fail_once():
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise RuntimeError("boom")
            return "ok"

        result = await with_retry(fail_once, breaker=cb, max_retries=1, base_delay=0.01)
        assert result == "ok"
        assert cb.failure_count == 0
        assert cb.state == "closed"


# ═══════════════════════════════════════════════════════════
# RED: 5xx 错误分类
# ═══════════════════════════════════════════════════════════


class TestErrorClassification5xx:
    """5xx 错误应被分类为可重试。"""

    def test_500_is_retryable(self):
        """HTTP 500 应被分类为 NETWORK（可重试）。"""
        from core.error_types import classify_error, ErrorCategory

        import httpx
        response = httpx.Response(500, text="error")
        err = httpx.HTTPStatusError("Server Error", request=httpx.Request("GET", "http://test"), response=response)

        cat = classify_error(err)
        assert cat in (ErrorCategory.NETWORK, ErrorCategory.UNKNOWN), f"5xx 应被重试，实际分类: {cat}"

    def test_429_is_rate_limit(self):
        """HTTP 429 被分类为 RATE_LIMIT。"""
        from core.error_types import classify_error, ErrorCategory

        import httpx
        response = httpx.Response(429, text="rate limited")
        err = httpx.HTTPStatusError("Rate Limited", request=httpx.Request("GET", "http://test"), response=response)

        cat = classify_error(err)
        assert cat == ErrorCategory.RATE_LIMIT

    def test_400_is_non_retryable(self):
        """HTTP 400 不应被重试。"""
        from core.error_types import classify_error, ErrorCategory

        import httpx
        response = httpx.Response(400, text="bad request")
        err = httpx.HTTPStatusError("Bad Request", request=httpx.Request("GET", "http://test"), response=response)

        cat = classify_error(err)
        assert cat in (ErrorCategory.NON_RETRYABLE, ErrorCategory.AUTH, ErrorCategory.NOT_FOUND)
