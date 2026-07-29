"""Token 限额接口测试。"""

import pytest
from unittest.mock import patch
from httpx import AsyncClient


@pytest.mark.asyncio
class TestQuotaAPI:
    """测试 /quota 接口。"""

    async def test_get_quota_status_disabled(self, client: AsyncClient, auth_headers: dict):
        """限额关闭时返回 enabled=False。"""
        with patch("api.qa.get_quota_status") as mock_status:
            mock_status.return_value = {
                "enabled": False,
                "used": 0,
                "limit": 10000,
                "remaining": 10000,
                "reset_at": None,
            }

            res = await client.get("/api/v1/qa/quota", headers=auth_headers)

            assert res.status_code == 200
            data = res.json()
            assert data["enabled"] is False
            assert data["used"] == 0
            assert data["limit"] == 10000

    async def test_get_quota_status_enabled(self, client: AsyncClient, auth_headers: dict):
        """限额启用时返回当前使用量。"""
        with patch("api.qa.get_quota_status") as mock_status:
            mock_status.return_value = {
                "enabled": True,
                "used": 3500,
                "limit": 10000,
                "remaining": 6500,
                "reset_at": "2026-07-30T00:00:00+00:00",
            }

            res = await client.get("/api/v1/qa/quota", headers=auth_headers)

            assert res.status_code == 200
            data = res.json()
            assert data["enabled"] is True
            assert data["used"] == 3500
            assert data["remaining"] == 6500
            assert data["reset_at"] is not None

    async def test_quota_api_requires_auth(self, client: AsyncClient):
        """未登录时返回 401。"""
        res = await client.get("/api/v1/qa/quota")
        assert res.status_code == 401