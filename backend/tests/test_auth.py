"""
鉴权模块测试：注册 / 登录 / Token 刷新。
"""

import pytest
from httpx import AsyncClient


# ── 注册 ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_register_success(client: AsyncClient):
    """正常注册 → 201 + 返回用户信息。"""
    email = "alice@example.com"
    
    await client.post("/api/v1/auth/send-code", json={"email": email})
    
    from services.verification_service import _in_memory_codes, _CODE_KEY_PREFIX
    code_key = f"{_CODE_KEY_PREFIX}{email}"
    code_entry = _in_memory_codes.get(code_key)
    verification_code = code_entry["code"] if code_entry else "123456"
    
    resp = await client.post(
        "/api/v1/auth/register",
        json={
            "username": "alice",
            "email": email,
            "password": "Abc12345!",
            "password_confirm": "Abc12345!",
            "verification_code": verification_code,
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["username"] == "alice"
    assert data["email"] == email
    assert "id" in data
    assert "created_at" in data


@pytest.mark.asyncio
async def test_register_duplicate_email(client: AsyncClient, registered_user: dict):
    """重复邮箱注册 → 409。"""
    email = registered_user["email"]
    
    await client.post("/api/v1/auth/send-code", json={"email": email})
    
    from services.verification_service import _in_memory_codes, _CODE_KEY_PREFIX
    code_key = f"{_CODE_KEY_PREFIX}{email}"
    code_entry = _in_memory_codes.get(code_key)
    verification_code = code_entry["code"] if code_entry else "123456"
    
    resp = await client.post(
        "/api/v1/auth/register",
        json={
            "username": "another",
            "email": email,
            "password": "Abc12345!",
            "password_confirm": "Abc12345!",
            "verification_code": verification_code,
        },
    )
    assert resp.status_code == 409
    err = resp.json()
    msg = err.get("error", {}).get("message", err.get("detail", ""))
    assert "已被注册" in msg


@pytest.mark.asyncio
async def test_register_password_mismatch(client: AsyncClient):
    """两次密码不一致 → 422。"""
    resp = await client.post(
        "/api/v1/auth/register",
        json={
            "username": "bob",
            "email": "bob@example.com",
            "password": "Abc12345!",
            "password_confirm": "Wrong123!",
        },
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_register_short_password(client: AsyncClient):
    """密码太短 → 422。"""
    resp = await client.post(
        "/api/v1/auth/register",
        json={
            "username": "charlie",
            "email": "charlie@example.com",
            "password": "123",
            "password_confirm": "123",
        },
    )
    assert resp.status_code == 422


# ── 登录 ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_login_success(client: AsyncClient, registered_user: dict):
    """正确邮箱+密码 → 200 + 返回双 token。"""
    resp = await client.post(
        "/api/v1/auth/login",
        json={
            "email": registered_user["email"],
            "password": registered_user["password"],
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["token_type"] == "bearer"


@pytest.mark.asyncio
async def test_login_wrong_password(client: AsyncClient, registered_user: dict):
    """密码错误 → 401。"""
    resp = await client.post(
        "/api/v1/auth/login",
        json={
            "email": registered_user["email"],
            "password": "WrongPassword!",
        },
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_login_nonexistent_email(client: AsyncClient):
    """不存在的邮箱 → 401。"""
    resp = await client.post(
        "/api/v1/auth/login",
        json={
            "email": "nobody@example.com",
            "password": "Whatever1!",
        },
    )
    assert resp.status_code == 401


# ── Token 刷新 ────────────────────────────────────────


@pytest.mark.asyncio
async def test_refresh_token_success(client: AsyncClient, registered_user: dict):
    """用 refresh_token 换新 token 对 → 200。"""
    # 先登录拿 refresh_token
    login_resp = await client.post(
        "/api/v1/auth/login",
        json={
            "email": registered_user["email"],
            "password": registered_user["password"],
        },
    )
    refresh = login_resp.json()["refresh_token"]

    # 用 refresh_token 刷新
    resp = await client.post(
        "/api/v1/auth/refresh",
        json={
            "refresh_token": refresh,
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert "refresh_token" in data


@pytest.mark.asyncio
async def test_refresh_with_access_token_fails(client: AsyncClient, registered_user: dict):
    """误用 access_token 做 refresh → 401。"""
    login_resp = await client.post(
        "/api/v1/auth/login",
        json={
            "email": registered_user["email"],
            "password": registered_user["password"],
        },
    )
    access = login_resp.json()["access_token"]

    resp = await client.post(
        "/api/v1/auth/refresh",
        json={
            "refresh_token": access,  # 用 access_token 冒充
        },
    )
    assert resp.status_code == 401
