"""产品分析 API 测试。

覆盖：
- TestEventRecording: POST /analytics/events 记录事件（200）/ 缺 event_name 校验（422）
- TestEventAuth: 未登录 → 401
- TestAdminList: 管理员可查列表，非管理员 → 403
- TestFunnel: 记录多条事件后，GET /analytics/funnel 返回聚合计数
- TestEventWiring: 注册用户 → user.register 事件已被记录
"""

import pytest
from httpx import AsyncClient

from models.analytics_event import AnalyticsEvent
from sqlalchemy import select


@pytest.fixture
async def admin_headers(client: AsyncClient, registered_user: dict, monkeypatch):
    """将测试用户设为管理员并登录（模式与 test_t34_admin.py 一致）。"""
    from core.config import settings

    monkeypatch.setattr(settings, "ADMIN_EMAILS", [registered_user["email"]])

    resp = await client.post(
        "/api/v1/auth/login",
        json={
            "email": registered_user["email"],
            "password": registered_user["password"],
        },
    )
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def normal_headers(client: AsyncClient):
    """普通（非管理员）用户登录头。"""
    await client.post("/api/v1/auth/send-code", json={"email": "normal@example.com"})
    from services.verification_service import _CODE_KEY_PREFIX, _in_memory_codes

    code_key = f"{_CODE_KEY_PREFIX}normal@example.com"
    code_entry = _in_memory_codes.get(code_key)
    verification_code = code_entry["code"] if code_entry else "123456"
    await client.post(
        "/api/v1/auth/register",
        json={
            "username": "normal",
            "email": "normal@example.com",
            "password": "Test1234!",
            "password_confirm": "Test1234!",
            "verification_code": verification_code,
        },
    )
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "normal@example.com", "password": "Test1234!"},
    )
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


# ═══════════════════════════════════════════════════════════
# 事件记录
# ═══════════════════════════════════════════════════════════


class TestEventRecording:
    async def test_record_event(self, client: AsyncClient, auth_headers: dict):
        r = await client.post(
            "/api/v1/track/events",
            headers=auth_headers,
            json={
                "event_name": "test.event",
                "source": "linkedin",
                "metadata": {"step": 1},
            },
        )
        assert r.status_code == 200
        data = r.json()
        assert data["event_name"] == "test.event"
        assert data["source"] == "linkedin"
        assert isinstance(data["id"], int)
        assert data["created_at"]

    async def test_missing_event_name_422(self, client: AsyncClient, auth_headers: dict):
        r = await client.post(
            "/api/v1/track/events",
            headers=auth_headers,
            json={"source": "linkedin"},
        )
        assert r.status_code == 422

    async def test_source_optional(self, client: AsyncClient, auth_headers: dict):
        r = await client.post(
            "/api/v1/track/events",
            headers=auth_headers,
            json={"event_name": "test.no_source"},
        )
        assert r.status_code == 200
        assert r.json()["source"] is None


# ═══════════════════════════════════════════════════════════
# 鉴权
# ═══════════════════════════════════════════════════════════


class TestEventAuth:
    async def test_unauthenticated_gets_401(self, client: AsyncClient):
        r = await client.post(
            "/api/v1/track/events", json={"event_name": "test.event"}
        )
        assert r.status_code == 401


# ═══════════════════════════════════════════════════════════
# 管理员列表
# ═══════════════════════════════════════════════════════════


class TestAdminList:
    async def test_admin_can_list_events(
        self, client: AsyncClient, admin_headers: dict, auth_headers: dict
    ):
        await client.post(
            "/api/v1/track/events", headers=auth_headers, json={"event_name": "test.a"}
        )
        await client.post(
            "/api/v1/track/events", headers=auth_headers, json={"event_name": "test.b"}
        )

        r = await client.get("/api/v1/track/events", headers=admin_headers)
        assert r.status_code == 200
        data = r.json()
        assert data["total"] >= 2
        names = {it["event_name"] for it in data["items"]}
        assert {"test.a", "test.b"} <= names

    async def test_filter_by_event_name(
        self, client: AsyncClient, admin_headers: dict, auth_headers: dict
    ):
        await client.post(
            "/api/v1/track/events", headers=auth_headers, json={"event_name": "test.a"}
        )
        await client.post(
            "/api/v1/track/events", headers=auth_headers, json={"event_name": "test.b"}
        )

        r = await client.get(
            "/api/v1/track/events?event_name=test.a", headers=admin_headers
        )
        assert r.status_code == 200
        data = r.json()
        assert data["total"] == 1
        assert data["items"][0]["event_name"] == "test.a"

    async def test_non_admin_gets_403(
        self, client: AsyncClient, normal_headers: dict
    ):
        r = await client.get("/api/v1/track/events", headers=normal_headers)
        assert r.status_code == 403


# ═══════════════════════════════════════════════════════════
# 漏斗聚合
# ═══════════════════════════════════════════════════════════


class TestFunnel:
    async def test_funnel_aggregates(
        self,
        client: AsyncClient,
        admin_headers: dict,
        auth_headers: dict,
        registered_user: dict,
    ):
        # registered_user 注册已埋 user.register（1 条，来源 None）
        await client.post(
            "/api/v1/track/events",
            headers=auth_headers,
            json={"event_name": "resume.upload", "source": "linkedin"},
        )
        await client.post(
            "/api/v1/track/events",
            headers=auth_headers,
            json={"event_name": "resume.upload", "source": "linkedin"},
        )
        await client.post(
            "/api/v1/track/events",
            headers=auth_headers,
            json={"event_name": "resume.export", "metadata": {"format": "pdf"}},
        )

        r = await client.get("/api/v1/track/funnel?days=30", headers=admin_headers)
        assert r.status_code == 200
        data = r.json()
        assert data["days"] == 30
        events = {e["event_name"]: e for e in data["events"]}

        assert events["user.register"]["count"] == 1
        assert events["resume.upload"]["count"] == 2
        assert events["resume.upload"]["unique_users"] == 1
        assert events["resume.export"]["count"] == 1
        assert events["resume.export"]["unique_users"] == 1

    async def test_funnel_days_param(
        self, client: AsyncClient, admin_headers: dict, auth_headers: dict
    ):
        r = await client.get("/api/v1/track/funnel?days=7", headers=admin_headers)
        assert r.status_code == 200
        assert r.json()["days"] == 7


# ═══════════════════════════════════════════════════════════
# 漏斗事件接线（注册 → user.register）
# ═══════════════════════════════════════════════════════════


class TestEventWiring:
    async def test_register_records_event(self, client: AsyncClient, db_session):
        await client.post("/api/v1/auth/send-code", json={"email": "wired@example.com"})
        from services.verification_service import _CODE_KEY_PREFIX, _in_memory_codes

        code_key = f"{_CODE_KEY_PREFIX}wired@example.com"
        code_entry = _in_memory_codes.get(code_key)
        verification_code = code_entry["code"] if code_entry else "123456"

        r = await client.post(
            "/api/v1/auth/register",
            json={
                "username": "wireduser",
                "email": "wired@example.com",
                "password": "Test1234!",
                "password_confirm": "Test1234!",
                "verification_code": verification_code,
                "source": "linkedin",
            },
        )
        assert r.status_code == 201

        result = await db_session.execute(
            select(AnalyticsEvent).where(
                AnalyticsEvent.event_name == "user.register"
            )
        )
        events = result.scalars().all()
        assert len(events) == 1
        assert events[0].source == "linkedin"
        assert events[0].user_id is not None
