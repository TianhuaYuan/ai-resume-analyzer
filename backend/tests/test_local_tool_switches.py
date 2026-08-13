"""
本地个人工具开关测试：注册免验证码（SKIP_EMAIL_VERIFICATION）+ 首用户管理员（BOOTSTRAP_FIRST_USER_ADMIN）。

- SKIP_EMAIL_VERIFICATION=True（默认）时注册无需有效验证码，直接 201。
- BOOTSTRAP_FIRST_USER_ADMIN=True 时首个注册用户 is_admin=True（空库判首）。
  代码默认 False 以保既有 403 断言；Docker compose 内置 true。
"""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_register_no_code_succeeds(client: AsyncClient):
    """SKIP_EMAIL_VERIFICATION=True 时注册无需有效验证码（占位码 000000 即通过）。"""
    resp = await client.post(
        "/api/v1/auth/register",
        json={
            "username": "noverify",
            "email": "noverify@example.com",
            "password": "Abc12345!",
            "password_confirm": "Abc12345!",
            "verification_code": "000000",
        },
    )
    assert resp.status_code == 201
    assert resp.json()["email"] == "noverify@example.com"


@pytest.mark.asyncio
async def test_first_user_becomes_admin(client: AsyncClient, monkeypatch):
    """BOOTSTRAP_FIRST_USER_ADMIN=True 时首个注册用户 /me 返回 is_admin=True。"""
    from core.config import settings

    monkeypatch.setattr(settings, "BOOTSTRAP_FIRST_USER_ADMIN", True)

    email = "firstadmin@example.com"
    resp = await client.post(
        "/api/v1/auth/register",
        json={
            "username": "firstadmin",
            "email": email,
            "password": "Abc12345!",
            "password_confirm": "Abc12345!",
            "verification_code": "000000",
        },
    )
    assert resp.status_code == 201

    login = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "Abc12345!"},
    )
    assert login.status_code == 200
    token = login.json()["access_token"]

    me = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert me.status_code == 200
    assert me.json()["is_admin"] is True
