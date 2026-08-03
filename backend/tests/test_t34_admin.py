"""T34: 管理员后台 API 测试。

覆盖：
- TestAdminAccess: 鉴权（401 未登录 / 403 非管理员 / 200 管理员）
- TestAdminAuditLogs: 列表 / action 过滤 / user_id 过滤 / 分页
- TestAdminUsers: 列表 / 分页
- TestAdminStats: 系统统计计数正确
- TestAdminTemplates: 模板列表返回 3 项
"""

import pytest
from httpx import AsyncClient

from models.audit_log import AuditLog


@pytest.fixture
async def admin_headers(client: AsyncClient, registered_user: dict, monkeypatch):
    """将测试用户设为管理员并登录。"""
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
    from services.verification_service import _in_memory_codes, _CODE_KEY_PREFIX

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


async def _seed_audit_logs(db_session, user_id: int, count: int = 5):
    """直接插入若干审计日志。"""
    for i in range(count):
        db_session.add(
            AuditLog(
                user_id=user_id,
                action="login" if i % 2 == 0 else "logout",
                target_type="user",
                target_id=str(user_id),
                detail={"idx": i},
                ip="127.0.0.1",
            )
        )
    await db_session.commit()


# ═══════════════════════════════════════════════════════════
# 鉴权
# ═══════════════════════════════════════════════════════════


class TestAdminAccess:
    async def test_unauthenticated_gets_401(self, client: AsyncClient):
        r = await client.get("/api/v1/admin/stats")
        assert r.status_code == 401

    async def test_non_admin_gets_403(self, client: AsyncClient, normal_headers: dict):
        r = await client.get("/api/v1/admin/stats", headers=normal_headers)
        assert r.status_code == 403

    async def test_admin_gets_200(self, client: AsyncClient, admin_headers: dict):
        r = await client.get("/api/v1/admin/stats", headers=admin_headers)
        assert r.status_code == 200


# ═══════════════════════════════════════════════════════════
# 审计日志
# ═══════════════════════════════════════════════════════════


class TestAdminAuditLogs:
    async def test_list_audit_logs(
        self, client: AsyncClient, admin_headers: dict, db_session, registered_user: dict
    ):
        await _seed_audit_logs(db_session, registered_user["id"], count=5)

        r = await client.get("/api/v1/admin/audit-logs", headers=admin_headers)
        assert r.status_code == 200
        data = r.json()
        assert data["total"] == 5
        assert len(data["items"]) == 5
        # 倒序，最新在前
        assert data["items"][0]["action"] in ("login", "logout")

    async def test_filter_by_action(
        self, client: AsyncClient, admin_headers: dict, db_session, registered_user: dict
    ):
        await _seed_audit_logs(db_session, registered_user["id"], count=4)

        r = await client.get(
            "/api/v1/admin/audit-logs?action=login", headers=admin_headers
        )
        assert r.status_code == 200
        data = r.json()
        # count=4 → idx 0,2 为 login（2 条），idx 1,3 为 logout
        assert data["total"] == 2
        assert all(it["action"] == "login" for it in data["items"])

    async def test_filter_by_user_id(
        self, client: AsyncClient, admin_headers: dict, db_session, registered_user: dict
    ):
        from models.user import User

        await _seed_audit_logs(db_session, registered_user["id"], count=3)

        # 创建第二个真实用户（外键约束要求 user_id 存在），其日志不应出现在过滤结果中
        other = User(
            username="other_user",
            email="other@example.com",
            password_hash="x",
        )
        db_session.add(other)
        await db_session.commit()
        await db_session.refresh(other)

        db_session.add(
            AuditLog(
                user_id=other.id,
                action="login",
                target_type="user",
                target_id=str(other.id),
            )
        )
        await db_session.commit()

        r = await client.get(
            f"/api/v1/admin/audit-logs?user_id={registered_user['id']}",
            headers=admin_headers,
        )
        assert r.status_code == 200
        data = r.json()
        assert data["total"] == 3
        assert all(it["user_id"] == registered_user["id"] for it in data["items"])

    async def test_pagination(
        self, client: AsyncClient, admin_headers: dict, db_session, registered_user: dict
    ):
        await _seed_audit_logs(db_session, registered_user["id"], count=5)

        r = await client.get(
            "/api/v1/admin/audit-logs?limit=2&offset=0", headers=admin_headers
        )
        assert r.status_code == 200
        data = r.json()
        assert data["total"] == 5
        assert len(data["items"]) == 2

        r2 = await client.get(
            "/api/v1/admin/audit-logs?limit=2&offset=2", headers=admin_headers
        )
        data2 = r2.json()
        assert len(data2["items"]) == 2
        # 两页 id 不重叠
        ids_page1 = {it["id"] for it in data["items"]}
        ids_page2 = {it["id"] for it in data2["items"]}
        assert ids_page1.isdisjoint(ids_page2)


# ═══════════════════════════════════════════════════════════
# 用户列表
# ═══════════════════════════════════════════════════════════


class TestAdminUsers:
    async def test_list_users(
        self, client: AsyncClient, admin_headers: dict, registered_user: dict
    ):
        r = await client.get("/api/v1/admin/users", headers=admin_headers)
        assert r.status_code == 200
        data = r.json()
        assert data["total"] >= 1
        # 安全字段：不应暴露 password_hash
        item = data["items"][0]
        assert "password_hash" not in item
        assert set(item.keys()) == {"id", "username", "email", "created_at"}

    async def test_users_pagination(
        self, client: AsyncClient, admin_headers: dict, normal_headers: dict
    ):
        # normal_headers fixture 注册了第二个用户
        r = await client.get(
            "/api/v1/admin/users?limit=1&offset=0", headers=admin_headers
        )
        assert r.status_code == 200
        data = r.json()
        assert data["total"] >= 2
        assert len(data["items"]) == 1


# ═══════════════════════════════════════════════════════════
# 系统统计
# ═══════════════════════════════════════════════════════════


class TestAdminStats:
    async def test_stats_counts(
        self, client: AsyncClient, admin_headers: dict, db_session, registered_user: dict
    ):
        # 注册用户已在 registered_user 中创建 1 个
        from models.user_feedback import UserFeedback

        db_session.add(
            UserFeedback(user_id=registered_user["id"], content="hi", type="bug")
        )
        await db_session.commit()

        r = await client.get("/api/v1/admin/stats", headers=admin_headers)
        assert r.status_code == 200
        data = r.json()
        assert data["total_users"] >= 1
        assert data["total_feedback"] >= 1
        # 字段齐全
        assert set(data.keys()) == {
            "total_users",
            "total_resumes",
            "total_qa_history",
            "total_feedback",
        }


# ═══════════════════════════════════════════════════════════
# 模板
# ═══════════════════════════════════════════════════════════


class TestAdminTemplates:
    async def test_templates_returns_three(self, client: AsyncClient, admin_headers: dict):
        r = await client.get("/api/v1/admin/templates", headers=admin_headers)
        assert r.status_code == 200
        data = r.json()
        assert len(data["templates"]) == 3
        ids = {t["id"] for t in data["templates"]}
        assert ids == {"default", "minimal", "business"}
        # 每项字段齐全
        for t in data["templates"]:
            assert set(t.keys()) == {"id", "name", "description"}
            assert t["description"]  # 非空
