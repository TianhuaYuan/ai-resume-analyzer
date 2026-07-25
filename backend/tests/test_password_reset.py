"""P1-23 方案 B：邮箱自助重置密码流程测试。

流程：
1. POST /api/v1/auth/forgot-password {email}
   - 始终返回 200（不泄露用户是否存在）
   - 若用户存在，生成 reset token（JWT, type="reset", 30min）
   - 开发环境：token 写入日志（生产环境对接邮件服务）

2. POST /api/v1/auth/reset-password {token, new_password}
   - 验证 token（decode + type=reset + 未撤销 + 未过期）
   - 更新密码 hash，撤销 token jti（一次性）
   - 新密码可登录
"""
import logging
import re

import pytest
from httpx import AsyncClient


def _extract_reset_token_from_logs(caplog) -> str | None:
    """从日志中提取重置 token。"""
    for record in caplog.records:
        m = re.search(r"reset_token=([^\s]+)", record.getMessage())
        if m:
            return m.group(1)
    return None


class TestForgotPassword:
    """忘记密码端点测试。"""

    async def test_forgot_password_existing_user_returns_200(
        self, client: AsyncClient, registered_user: dict, caplog
    ):
        """已注册用户请求重置应返回 200，并生成 token 写入日志。"""
        caplog.set_level(logging.INFO, logger="services.auth_service")
        r = await client.post(
            "/api/v1/auth/forgot-password",
            json={"email": registered_user["email"]},
        )
        assert r.status_code == 200
        assert "detail" in r.json()

        token = _extract_reset_token_from_logs(caplog)
        assert token is not None, "应在日志中记录 reset_token 供开发环境使用"
        assert len(token) > 20, "token 应有足够长度"

    async def test_forgot_password_nonexistent_user_returns_200(
        self, client: AsyncClient, caplog
    ):
        """不存在的邮箱也返回 200，防止用户枚举攻击。"""
        caplog.set_level(logging.INFO, logger="services.auth_service")
        r = await client.post(
            "/api/v1/auth/forgot-password",
            json={"email": "nonexistent@example.com"},
        )
        assert r.status_code == 200
        # 不存在的用户不应生成 token
        token = _extract_reset_token_from_logs(caplog)
        assert token is None, "不存在的用户不应生成 reset token"

    async def test_forgot_password_invalid_email_format(
        self, client: AsyncClient
    ):
        """邮箱格式非法应返回 422。"""
        r = await client.post(
            "/api/v1/auth/forgot-password",
            json={"email": "not-an-email"},
        )
        assert r.status_code == 422


class TestResetPassword:
    """重置密码端点测试。"""

    async def _get_reset_token(
        self, client: AsyncClient, email: str, caplog
    ) -> str:
        """辅助：请求忘记密码并返回生成的 token。"""
        caplog.set_level(logging.INFO, logger="services.auth_service")
        await client.post("/api/v1/auth/forgot-password", json={"email": email})
        token = _extract_reset_token_from_logs(caplog)
        assert token is not None, "未能从日志提取 reset token"
        return token

    async def test_reset_password_success(
        self, client: AsyncClient, registered_user: dict, caplog
    ):
        """完整流程：忘记密码 → 拿 token → 重置 → 新密码可登录。"""
        token = await self._get_reset_token(
            client, registered_user["email"], caplog
        )

        new_password = "NewPass123!"
        r = await client.post(
            "/api/v1/auth/reset-password",
            json={"token": token, "new_password": new_password},
        )
        assert r.status_code == 200
        assert "detail" in r.json()

        # 旧密码应失败
        old_login = await client.post(
            "/api/v1/auth/login",
            json={
                "email": registered_user["email"],
                "password": registered_user["password"],
            },
        )
        assert old_login.status_code == 401

        # 新密码应成功
        new_login = await client.post(
            "/api/v1/auth/login",
            json={"email": registered_user["email"], "password": new_password},
        )
        assert new_login.status_code == 200

    async def test_reset_password_invalid_token(self, client: AsyncClient):
        """无效 token 应返回 400。"""
        r = await client.post(
            "/api/v1/auth/reset-password",
            json={"token": "invalid.token.here", "new_password": "NewPass123!"},
        )
        assert r.status_code == 400

    async def test_reset_password_wrong_type_token(
        self, client: AsyncClient, auth_headers: dict
    ):
        """使用 access token（type≠reset）应返回 400。"""
        # auth_headers 中的 Authorization: Bearer xxx
        access_token = auth_headers["Authorization"].replace("Bearer ", "")
        r = await client.post(
            "/api/v1/auth/reset-password",
            json={"token": access_token, "new_password": "NewPass123!"},
        )
        assert r.status_code == 400

    async def test_reset_password_already_used(
        self, client: AsyncClient, registered_user: dict, caplog
    ):
        """已使用过的 reset token 不能再次使用（一次性）。"""
        token = await self._get_reset_token(
            client, registered_user["email"], caplog
        )

        # 第一次使用：成功
        r1 = await client.post(
            "/api/v1/auth/reset-password",
            json={"token": token, "new_password": "First123!"},
        )
        assert r1.status_code == 200

        # 第二次使用：失败（已撤销）
        r2 = await client.post(
            "/api/v1/auth/reset-password",
            json={"token": token, "new_password": "Second123!"},
        )
        assert r2.status_code == 400

    async def test_reset_password_weak_password(
        self, client: AsyncClient, registered_user: dict, caplog
    ):
        """弱密码应返回 422。"""
        token = await self._get_reset_token(
            client, registered_user["email"], caplog
        )

        # 密码太短
        r = await client.post(
            "/api/v1/auth/reset-password",
            json={"token": token, "new_password": "short1"},
        )
        assert r.status_code == 422

    async def test_reset_password_missing_digit(
        self, client: AsyncClient, registered_user: dict, caplog
    ):
        """密码缺少数字应返回 422。"""
        token = await self._get_reset_token(
            client, registered_user["email"], caplog
        )

        r = await client.post(
            "/api/v1/auth/reset-password",
            json={"token": token, "new_password": "NoDigitHere!"},
        )
        assert r.status_code == 422

    async def test_reset_password_missing_letter(
        self, client: AsyncClient, registered_user: dict, caplog
    ):
        """密码缺少字母应返回 422。"""
        token = await self._get_reset_token(
            client, registered_user["email"], caplog
        )

        r = await client.post(
            "/api/v1/auth/reset-password",
            json={"token": token, "new_password": "12345678901"},
        )
        assert r.status_code == 422
