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


# ── 修改密码 ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_change_password_with_old_password(client: AsyncClient, auth_headers: dict, registered_user: dict):
    """旧密码验证修改密码 → 200。"""
    resp = await client.put(
        "/api/v1/auth/password",
        json={
            "mode": "password",
            "old_password": registered_user["password"],
            "new_password": "NewPass123!",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_change_password_wrong_old_password(client: AsyncClient, auth_headers: dict, registered_user: dict):
    """旧密码错误 → 400。"""
    resp = await client.put(
        "/api/v1/auth/password",
        json={
            "mode": "password",
            "old_password": "WrongPassword!",
            "new_password": "NewPass123!",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_change_password_with_code(client: AsyncClient, auth_headers: dict, registered_user: dict):
    """邮箱验证码修改密码 → 200。"""
    email = registered_user["email"]
    await client.post("/api/v1/auth/send-code", json={"email": email})
    from services.verification_service import _in_memory_codes, _CODE_KEY_PREFIX
    code_key = f"{_CODE_KEY_PREFIX}{email}"
    code_entry = _in_memory_codes.get(code_key)
    verification_code = code_entry["code"] if code_entry else "123456"

    resp = await client.put(
        "/api/v1/auth/password",
        json={
            "mode": "code",
            "verification_code": verification_code,
            "new_password": "NewPass123!",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_change_password_weak(client: AsyncClient, auth_headers: dict, registered_user: dict):
    """新密码强度不够 → 422。"""
    resp = await client.put(
        "/api/v1/auth/password",
        json={
            "mode": "password",
            "old_password": registered_user["password"],
            "new_password": "123",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_change_password_unauthorized(client: AsyncClient):
    """未登录 → 401。"""
    resp = await client.put(
        "/api/v1/auth/password",
        json={
            "mode": "password",
            "old_password": "Test1234!",
            "new_password": "NewPass123!",
        },
    )
    assert resp.status_code == 401


# ── 修改邮箱 ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_change_email_success(client: AsyncClient, auth_headers: dict):
    """修改邮箱 → 200。"""
    new_email = "newemail@example.com"
    await client.post("/api/v1/auth/send-code", json={"email": new_email})
    from services.verification_service import _in_memory_codes, _CODE_KEY_PREFIX
    code_key = f"{_CODE_KEY_PREFIX}{new_email}"
    code_entry = _in_memory_codes.get(code_key)
    verification_code = code_entry["code"] if code_entry else "123456"

    resp = await client.put(
        "/api/v1/auth/email",
        json={
            "new_email": new_email,
            "verification_code": verification_code,
        },
        headers=auth_headers,
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_change_email_duplicate(client: AsyncClient, auth_headers: dict, registered_user: dict):
    """新邮箱已被注册 → 409。先注册另一个用户。"""
    email2 = "another@example.com"
    await client.post("/api/v1/auth/send-code", json={"email": email2})
    from services.verification_service import _in_memory_codes, _CODE_KEY_PREFIX
    code_key = f"{_CODE_KEY_PREFIX}{email2}"
    code_entry = _in_memory_codes.get(code_key)
    verification_code = code_entry["code"] if code_entry else "123456"
    await client.post(
        "/api/v1/auth/register",
        json={
            "username": "another",
            "email": email2,
            "password": "Abc12345!",
            "password_confirm": "Abc12345!",
            "verification_code": verification_code,
        },
    )

    # 尝试绑定已存在的邮箱
    new_email = email2
    await client.post("/api/v1/auth/send-code", json={"email": new_email})
    code_key = f"{_CODE_KEY_PREFIX}{new_email}"
    code_entry = _in_memory_codes.get(code_key)
    verification_code = code_entry["code"] if code_entry else "123456"

    resp = await client.put(
        "/api/v1/auth/email",
        json={
            "new_email": new_email,
            "verification_code": verification_code,
        },
        headers=auth_headers,
    )
    assert resp.status_code == 409


# ── 修改用户名 ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_change_username_success(client: AsyncClient, auth_headers: dict):
    """修改用户名 → 200。"""
    resp = await client.put(
        "/api/v1/auth/username",
        json={
            "new_username": "newusername",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_change_username_duplicate(client: AsyncClient, auth_headers: dict, registered_user: dict):
    """用户名已被注册 → 409。"""
    resp = await client.put(
        "/api/v1/auth/username",
        json={
            "new_username": registered_user["username"],  # 与当前用户名相同
        },
        headers=auth_headers,
    )
    assert resp.status_code == 400  # 相同用户名应被拒绝


@pytest.mark.asyncio
async def test_change_username_too_short(client: AsyncClient, auth_headers: dict):
    """用户名太短 → 422。"""
    resp = await client.put(
        "/api/v1/auth/username",
        json={
            "new_username": "a",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 422
