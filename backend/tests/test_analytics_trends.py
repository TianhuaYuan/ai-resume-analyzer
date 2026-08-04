"""D3/D4: 后台看板趋势 + LLM 用量历史 API 测试。

覆盖：
- /track/trends：按天聚合注册/日活/事件数；非 admin 403
- /track/llm-usage：Redis 记账读取聚合；非 admin 403；Redis 不可用返回空
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from tests.conftest import AsyncSessionTest


@pytest.fixture
async def admin_headers(client: AsyncClient, registered_user: dict, monkeypatch):
    """将测试用户设为管理员并登录（模式与 test_t37_analytics.py 一致）。"""
    from core.config import settings

    monkeypatch.setattr(settings, "ADMIN_EMAILS", [registered_user["email"]])
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": registered_user["email"], "password": registered_user["password"]},
    )
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


async def _seed_events(user_id: int, days_ago: int = 0, count: int = 3) -> None:
    """为用户插入 count 条 N 天前的事件。"""
    from models.analytics_event import AnalyticsEvent

    ts = datetime.now(timezone.utc) - timedelta(days=days_ago)
    async with AsyncSessionTest() as session:
        for i in range(count):
            session.add(
                AnalyticsEvent(user_id=user_id, event_name="resume.upload", created_at=ts)
            )
        await session.commit()


# ── D3: /track/trends ─────────────────────────────────────


@pytest.mark.asyncio
async def test_trends_requires_admin(client: AsyncClient, auth_headers: dict):
    """非 admin → 403。"""
    resp = await client.get("/api/v1/track/trends", headers=auth_headers)
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_trends_groups_by_day(
    client: AsyncClient, admin_headers: dict, registered_user: dict
):
    """趋势按天聚合：事件数 + 活跃用户 + 注册数。"""
    await _seed_events(registered_user["id"], days_ago=0, count=3)
    await _seed_events(registered_user["id"], days_ago=2, count=1)

    resp = await client.get("/api/v1/track/trends?days=7", headers=admin_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["days"] == 7
    assert len(data["items"]) >= 1

    today = (datetime.now(timezone.utc)).date().isoformat()
    today_entry = next((i for i in data["items"] if i["day"] == today), None)
    assert today_entry is not None
    assert today_entry["events"] >= 3  # 3 条自定义事件 + 注册等系统埋点
    assert today_entry["active_users"] == 1
    assert today_entry["registrations"] == 1  # 测试用户当天注册


# ── D4: /track/llm-usage ──────────────────────────────────


class _FakeRedis:
    """模拟 Redis：keys(glob) + get(int str)。"""

    def __init__(self, data: dict):
        self.data = data

    async def keys(self, pattern: str):
        parts = pattern.split("*")
        prefix, suffix = parts[0], parts[-1]  # 支持多个 *（如 llm_usage:*:*:total）
        return [k for k in self.data if k.startswith(prefix) and k.endswith(suffix)]

    async def get(self, key: str):
        return self.data.get(key)


@pytest.mark.asyncio
async def test_llm_usage_requires_admin(client: AsyncClient, auth_headers: dict):
    """非 admin → 403。"""
    resp = await client.get("/api/v1/track/llm-usage", headers=auth_headers)
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_llm_usage_aggregates_by_day(
    client: AsyncClient, admin_headers: dict
):
    """用量按天聚合 total/calls（跨用户）。"""
    fake = _FakeRedis(
        {
            "llm_usage:1:20260801:total": "100",
            "llm_usage:1:20260801:calls": "2",
            "llm_usage:2:20260801:total": "50",
            "llm_usage:2:20260801:calls": "1",
            "llm_usage:1:20260802:total": "30",
            "llm_usage:1:20260802:calls": "1",
        }
    )
    with patch("services.rag.usage.get_redis", new_callable=AsyncMock, return_value=fake):
        resp = await client.get("/api/v1/track/llm-usage?days=7", headers=admin_headers)

    assert resp.status_code == 200
    items = resp.json()["items"]
    day1 = next(i for i in items if i["date"] == "20260801")
    assert day1["total_tokens"] == 150
    assert day1["calls"] == 3
    day2 = next(i for i in items if i["date"] == "20260802")
    assert day2["total_tokens"] == 30


@pytest.mark.asyncio
async def test_llm_usage_redis_failure_returns_empty(
    client: AsyncClient, admin_headers: dict
):
    """Redis 不可用 → 返回空列表（优雅降级）。"""
    with patch(
        "services.rag.usage.get_redis", side_effect=RuntimeError("redis down")
    ):
        resp = await client.get("/api/v1/track/llm-usage", headers=admin_headers)

    assert resp.status_code == 200
    assert resp.json()["items"] == []
