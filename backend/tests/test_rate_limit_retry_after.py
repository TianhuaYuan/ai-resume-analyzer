"""限流响应应包含 Retry-After 头，让用户知道多久后可重试。"""

from unittest.mock import MagicMock

import pytest
from slowapi.errors import RateLimitExceeded

from main import rate_limit_handler


@pytest.mark.asyncio
async def test_rate_limit_response_includes_retry_after_header():
    """429 响应必须包含 Retry-After 头。"""
    # 构造一个 RateLimitExceeded 异常
    fake_limit = MagicMock()
    fake_limit.amount = 1
    fake_limit.period = 60
    exc = RateLimitExceeded(fake_limit)

    request = MagicMock()
    response = await rate_limit_handler(request, exc)

    assert response.status_code == 429
    # Retry-After 头存在且为正整数
    retry_after = response.headers.get("Retry-After")
    assert retry_after is not None
    assert int(retry_after) > 0


@pytest.mark.asyncio
async def test_rate_limit_response_body_contains_wait_hint():
    """响应体应包含可读的等待提示。"""
    fake_limit = MagicMock()
    fake_limit.amount = 1
    fake_limit.period = 60
    exc = RateLimitExceeded(fake_limit)

    request = MagicMock()
    response = await rate_limit_handler(request, exc)

    body = response.body.decode("utf-8")
    assert "稍后" in body or "retry" in body.lower() or "秒" in body
