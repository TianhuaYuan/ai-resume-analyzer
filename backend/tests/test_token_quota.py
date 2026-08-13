"""Token 限额服务测试。"""

import pytest
from unittest.mock import AsyncMock, patch

from services.token_quota import (
    check_quota,
    record_usage,
    get_quota_status,
    _get_today_key,
)


@pytest.fixture
def mock_settings():
    """Mock settings with quota enabled."""
    with patch("services.token_quota.settings") as mock:
        mock.TOKEN_QUOTA_ENABLED = True
        mock.TOKEN_QUOTA_DAILY_LIMIT = 10000
        mock.TOKEN_QUOTA_MIN_RESERVE = 500
        yield mock


@pytest.fixture
def mock_redis():
    """Mock Redis client."""
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    redis.incrby = AsyncMock(return_value=100)
    redis.expire = AsyncMock()
    return redis


class TestGetTodayKey:
    """测试 Redis key 生成。"""

    def test_key_format(self):
        """key 格式应为 token_quota:{user_id}:{YYYY-MM-DD}"""
        key = _get_today_key(123)
        assert key.startswith("token_quota:123:")
        assert len(key.split(":")) == 3
        # 日期部分应该是 YYYY-MM-DD 格式
        date_part = key.split(":")[-1]
        assert len(date_part) == 10  # 2026-07-29
        assert date_part.count("-") == 2


class TestGetQuotaStatus:
    """测试获取限额状态。"""

    @pytest.mark.asyncio
    async def test_returns_disabled_when_quota_off(self):
        """限额关闭时返回 enabled=False。"""
        with patch("services.token_quota.settings") as mock:
            mock.TOKEN_QUOTA_ENABLED = False
            mock.TOKEN_QUOTA_DAILY_LIMIT = 10000

            result = await get_quota_status(1)

            assert result["enabled"] is False
            assert result["used"] == 0
            assert result["limit"] == 10000

    @pytest.mark.asyncio
    async def test_returns_current_usage(self, mock_settings, mock_redis):
        """返回当前使用量。"""
        mock_redis.get = AsyncMock(return_value="3500")

        with patch("services.token_quota.get_redis", AsyncMock(return_value=mock_redis)):
            result = await get_quota_status(1)

            assert result["enabled"] is True
            assert result["used"] == 3500
            assert result["remaining"] == 6500
            assert result["limit"] == 10000
            assert result["reset_at"] is not None

    @pytest.mark.asyncio
    async def test_handles_redis_unavailable(self, mock_settings):
        """Redis 不可用时返回无限制。"""
        with patch("services.token_quota.get_redis", AsyncMock(return_value=None)):
            result = await get_quota_status(1)

            assert result["enabled"] is True
            assert result["remaining"] == 10000


class TestCheckQuota:
    """测试预检查逻辑。"""

    @pytest.mark.asyncio
    async def test_allows_when_quota_disabled(self):
        """限额关闭时放行。"""
        with patch("services.token_quota.settings") as mock:
            mock.TOKEN_QUOTA_ENABLED = False

            allowed, error = await check_quota(1)

            assert allowed is True
            assert error is None

    @pytest.mark.asyncio
    async def test_allows_when_under_limit(self, mock_settings, mock_redis):
        """额度充足时放行。"""
        mock_redis.get = AsyncMock(return_value="5000")  # 已用 5000

        with patch("services.token_quota.get_redis", AsyncMock(return_value=mock_redis)):
            allowed, error = await check_quota(1)

            assert allowed is True
            assert error is None

    @pytest.mark.asyncio
    async def test_rejects_when_over_limit(self, mock_settings, mock_redis):
        """额度不足时拒绝。"""
        mock_redis.get = AsyncMock(return_value="9800")  # 已用 9800，剩余 200

        with patch("services.token_quota.get_redis", AsyncMock(return_value=mock_redis)):
            allowed, error = await check_quota(1)

            assert allowed is False
            assert "额度已用完" in error
            assert "200" in error

    @pytest.mark.asyncio
    async def test_rejects_when_exactly_at_limit(self, mock_settings, mock_redis):
        """刚好到限额时拒绝。"""
        mock_redis.get = AsyncMock(return_value="10000")  # 已用完

        with patch("services.token_quota.get_redis", AsyncMock(return_value=mock_redis)):
            allowed, error = await check_quota(1)

            assert allowed is False
            assert error is not None

    @pytest.mark.asyncio
    async def test_allows_on_redis_error(self, mock_settings):
        """Redis 出错时放行，避免影响用户体验。"""
        with patch("services.token_quota.get_redis", AsyncMock(side_effect=Exception("Redis down"))):
            allowed, error = await check_quota(1)

            assert allowed is True
            assert error is None


class TestRecordUsage:
    """测试记录消耗。"""

    @pytest.mark.asyncio
    async def test_does_nothing_when_quota_disabled(self):
        """限额关闭时不记录。"""
        with patch("services.token_quota.settings") as mock:
            mock.TOKEN_QUOTA_ENABLED = False

            result = await record_usage(1, 100, 200)

            assert result == 0

    @pytest.mark.asyncio
    async def test_records_total_tokens(self, mock_settings, mock_redis):
        """记录 prompt + completion 总和。"""
        with patch("services.token_quota.get_redis", AsyncMock(return_value=mock_redis)):
            result = await record_usage(1, 150, 250)

            mock_redis.incrby.assert_called_once()
            # 检查传入的 key 和值
            call_args = mock_redis.incrby.call_args
            assert "token_quota:1:" in call_args[0][0]
            assert call_args[0][1] == 400  # 150 + 250

    @pytest.mark.asyncio
    async def test_sets_ttl_on_new_key(self, mock_settings, mock_redis):
        """新 key 设置过期时间。"""
        mock_redis.incrby = AsyncMock(return_value=100)  # 返回值等于新增值，说明是新 key

        with patch("services.token_quota.get_redis", AsyncMock(return_value=mock_redis)):
            await record_usage(1, 50, 50)

            mock_redis.expire.assert_called_once()

    @pytest.mark.asyncio
    async def test_does_not_set_ttl_on_existing_key(self, mock_settings, mock_redis):
        """已存在的 key 不设置过期时间。"""
        mock_redis.incrby = AsyncMock(return_value=500)  # 返回值大于新增值，说明 key 已存在

        with patch("services.token_quota.get_redis", AsyncMock(return_value=mock_redis)):
            await record_usage(1, 50, 50)

            # 已存在的 key 不需要再设置 TTL
            mock_redis.expire.assert_not_called()