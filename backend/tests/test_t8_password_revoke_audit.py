"""T8: 改密撤销 + DELETE /auth/account + audit_log。

测试范围：
- 改密后旧 token（iat < password_changed_at）被拒绝
- refresh_token 在改密后同样被拒绝
- DELETE /auth/account 级联清理用户所有数据
- audit_log 在关键操作后被异步写入
"""

import asyncio

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from models.audit_log import AuditLog
from models.user import User


async def _wait_next_second() -> None:
    """等待越过下一秒边界。

    JWT iat 只有秒级精度，改密撤销用 `iat < password_changed_at` 判定。
    登录与改密若落在同一秒，iat == password_changed_at → 旧 token 不被判定为失效。
    等待 ≥1s 保证改密时刻处于登录时刻的严格下一秒，使撤销判定确定。
    """
    await asyncio.sleep(1.1)


# ═══════════════════════════════════════════════════════════
# 改密撤销
# ═══════════════════════════════════════════════════════════


class TestPasswordChangeRevoke:
    """改密后旧 token 应失效（iat 校验）。"""

    @pytest.mark.asyncio
    async def test_old_token_rejected_after_password_change(
        self, client: AsyncClient, registered_user: dict, auth_headers: dict
    ):
        """改密后，用旧 access_token 访问 /me 应返回 401。"""
        # 等待越过下一秒边界：保证 access token 的 iat 早于 password_changed_at
        await _wait_next_second()
        # 1. 改密
        resp = await client.put(
            "/api/v1/auth/password",
            json={
                "mode": "password",
                "old_password": registered_user["password"],
                "new_password": "NewPass123!",
                "new_password_confirm": "NewPass123!",
            },
            headers=auth_headers,
        )
        assert resp.status_code == 200

        # 2. 用旧 token 访问 /me
        resp = await client.get("/api/v1/auth/me", headers=auth_headers)
        assert resp.status_code == 401
        body = resp.json()
        msg = body.get("detail") or body.get("error", {}).get("message", "")
        assert "密码已修改" in msg or "失效" in msg

    @pytest.mark.asyncio
    async def test_new_token_accepted_after_password_change(
        self, client: AsyncClient, registered_user: dict, auth_headers: dict
    ):
        """改密后，用新签发的 token 应正常访问。"""
        # 1. 改密
        resp = await client.put(
            "/api/v1/auth/password",
            json={
                "mode": "password",
                "old_password": registered_user["password"],
                "new_password": "NewPass123!",
                "new_password_confirm": "NewPass123!",
            },
            headers=auth_headers,
        )
        assert resp.status_code == 200

        # 2. 用新密码登录
        resp = await client.post(
            "/api/v1/auth/login",
            json={
                "email": registered_user["email"],
                "password": "NewPass123!",
            },
        )
        assert resp.status_code == 200
        new_token = resp.json()["access_token"]

        # 3. 新 token 访问 /me
        resp = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {new_token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["email"] == registered_user["email"]

    @pytest.mark.asyncio
    async def test_refresh_token_rejected_after_password_change(
        self, client: AsyncClient, registered_user: dict, auth_headers: dict
    ):
        """改密后，用旧 refresh_token 刷新应返回 401。"""
        # 先登录获取 refresh_token
        resp = await client.post(
            "/api/v1/auth/login",
            json={
                "email": registered_user["email"],
                "password": registered_user["password"],
            },
        )
        refresh_token = resp.json()["refresh_token"]

        # 等待越过下一秒边界：保证 refresh token 的 iat 早于 password_changed_at
        await _wait_next_second()

        # 改密
        resp = await client.put(
            "/api/v1/auth/password",
            json={
                "mode": "password",
                "old_password": registered_user["password"],
                "new_password": "NewPass123!",
                "new_password_confirm": "NewPass123!",
            },
            headers=auth_headers,
        )
        assert resp.status_code == 200

        # 用旧 refresh_token 刷新
        resp = await client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": refresh_token},
        )
        assert resp.status_code == 401


# ═══════════════════════════════════════════════════════════
# DELETE /auth/account
# ═══════════════════════════════════════════════════════════


class TestDeleteAccount:
    """删账户级联清理。"""

    @pytest.mark.asyncio
    async def test_delete_account_returns_204(
        self, client: AsyncClient, registered_user: dict, auth_headers: dict
    ):
        """删除账户应返回 204。"""
        resp = await client.delete("/api/v1/auth/account", headers=auth_headers)
        assert resp.status_code == 204

    @pytest.mark.asyncio
    async def test_delete_account_removes_user(
        self, client: AsyncClient, registered_user: dict, auth_headers: dict
    ):
        """删除账户后用户应从 DB 中消失。"""
        user_id = registered_user["id"]
        await client.delete("/api/v1/auth/account", headers=auth_headers)

        from tests.conftest import AsyncSessionTest
        async with AsyncSessionTest() as db:
            result = await db.execute(select(User).where(User.id == user_id))
            user = result.scalar_one_or_none()
            assert user is None

    @pytest.mark.asyncio
    async def test_old_token_rejected_after_account_deletion(
        self, client: AsyncClient, registered_user: dict, auth_headers: dict
    ):
        """删除账户后旧 token 应 401。"""
        await client.delete("/api/v1/auth/account", headers=auth_headers)

        resp = await client.get("/api/v1/auth/me", headers=auth_headers)
        assert resp.status_code == 401


# ═══════════════════════════════════════════════════════════
# audit_log
# ═══════════════════════════════════════════════════════════


class TestAuditLog:
    """审计日志异步写入。"""

    @pytest.mark.asyncio
    async def test_password_change_creates_audit_log(
        self, client: AsyncClient, registered_user: dict, auth_headers: dict
    ):
        """改密操作应写入 audit_log。"""
        user_id = registered_user["id"]

        resp = await client.put(
            "/api/v1/auth/password",
            json={
                "mode": "password",
                "old_password": registered_user["password"],
                "new_password": "NewPass123!",
                "new_password_confirm": "NewPass123!",
            },
            headers=auth_headers,
        )
        assert resp.status_code == 200

        # 使用独立会话查询已提交的审计日志
        from tests.conftest import AsyncSessionTest
        async with AsyncSessionTest() as db:
            result = await db.execute(
                select(AuditLog).where(
                    AuditLog.user_id == user_id,
                    AuditLog.action == "change_password",
                )
            )
            log = result.scalar_one_or_none()
            assert log is not None
            assert log.target_type == "user"

    @pytest.mark.asyncio
    async def test_delete_account_creates_audit_log(
        self, client: AsyncClient, registered_user: dict, auth_headers: dict
    ):
        """删账户操作应写入 audit_log。"""
        user_id = registered_user["id"]

        resp = await client.delete("/api/v1/auth/account", headers=auth_headers)
        assert resp.status_code == 204

        from tests.conftest import AsyncSessionTest
        async with AsyncSessionTest() as db:
            # S1-T8: 删账户后 user_id 因 ondelete=SET NULL 变为 None，
            # 需通过 action + target_id 定位日志
            result = await db.execute(
                select(AuditLog).where(
                    AuditLog.action == "delete_account",
                    AuditLog.target_id == str(user_id),
                )
            )
            log = result.scalar_one_or_none()
            assert log is not None
