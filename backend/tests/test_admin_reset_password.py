"""P1-23: 管理员重置密码功能测试。

方案 A：管理员后台手动重置密码 API
- POST /api/v1/auth/admin/reset-password
- 仅管理员可调用（settings.ADMIN_EMAILS 中的邮箱）
- 返回新的临时密码
"""
import pytest
from httpx import AsyncClient


@pytest.fixture
async def admin_headers(client, registered_user, monkeypatch):
    """将测试用户设为管理员并登录。"""
    from core.config import settings
    monkeypatch.setattr(settings, "ADMIN_EMAILS", [registered_user["email"]])

    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": registered_user["email"], "password": registered_user["password"]},
    )
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def normal_user_headers(client):
    """普通用户（非管理员）登录。"""
    await client.post(
        "/api/v1/auth/register",
        json={
            "username": "normal",
            "email": "normal@example.com",
            "password": "Test1234!",
            "password_confirm": "Test1234!",
        },
    )
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "normal@example.com", "password": "Test1234!"},
    )
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


async def test_admin_reset_password_success(
    client: AsyncClient, admin_headers: dict, registered_user: dict
):
    """管理员重置密码应返回新密码，且新密码可登录。"""
    # 创建目标用户
    await client.post(
        "/api/v1/auth/register",
        json={
            "username": "target",
            "email": "target@example.com",
            "password": "OldPass123!",
            "password_confirm": "OldPass123!",
        },
    )

    r = await client.post(
        "/api/v1/auth/admin/reset-password",
        json={"email": "target@example.com"},
        headers=admin_headers,
    )
    assert r.status_code == 200
    data = r.json()
    assert "new_password" in data
    assert data["email"] == "target@example.com"

    # 新密码应可登录
    login_r = await client.post(
        "/api/v1/auth/login",
        json={"email": "target@example.com", "password": data["new_password"]},
    )
    assert login_r.status_code == 200


async def test_admin_reset_password_non_admin_forbidden(
    client: AsyncClient, normal_user_headers: dict
):
    """非管理员调用应返回 403。"""
    r = await client.post(
        "/api/v1/auth/admin/reset-password",
        json={"email": "someone@example.com"},
        headers=normal_user_headers,
    )
    assert r.status_code == 403


async def test_admin_reset_password_user_not_found(
    client: AsyncClient, admin_headers: dict
):
    """重置不存在的用户应返回 404。"""
    r = await client.post(
        "/api/v1/auth/admin/reset-password",
        json={"email": "nonexistent@example.com"},
        headers=admin_headers,
    )
    assert r.status_code == 404


async def test_admin_reset_password_requires_auth(client: AsyncClient):
    """未登录调用应返回 401。"""
    r = await client.post(
        "/api/v1/auth/admin/reset-password",
        json={"email": "someone@example.com"},
    )
    assert r.status_code == 401
