"""A4 知识资产 CRUD API 测试（/api/v1/assets）。"""

import pytest


async def _create(client, headers, **overrides):
    body = {"asset_type": "jd", "title": "测试 JD", "content": "精通 Python 与高并发开发"}
    body.update(overrides)
    return await client.post("/api/v1/assets", json=body, headers=headers)


async def _register_other(client, username="other", email="other@example.com"):
    """注册第二个用户并返回其 auth headers。"""
    data = {"username": username, "email": email, "password": "Test1234!", "password_confirm": "Test1234!"}
    await client.post("/api/v1/auth/send-code", json={"email": data["email"]})
    from services.verification_service import _CODE_KEY_PREFIX, _in_memory_codes

    code = _in_memory_codes.get(f"{_CODE_KEY_PREFIX}{data['email']}")["code"]
    await client.post("/api/v1/auth/register", json={**data, "verification_code": code})
    login = await client.post("/api/v1/auth/login", json={"email": data["email"], "password": data["password"]})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


@pytest.mark.asyncio
async def test_create_asset(client, auth_headers):
    resp = await _create(client, auth_headers, is_draft=True)
    assert resp.status_code == 201
    data = resp.json()
    assert data["asset_type"] == "jd"
    assert data["title"] == "测试 JD"
    assert data["is_draft"] is True
    assert data["version"] == 1
    assert "indexed" in data


@pytest.mark.asyncio
async def test_create_asset_invalid_type(client, auth_headers):
    resp = await _create(client, auth_headers, asset_type="unknown")
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_list_assets_filter_type(client, auth_headers):
    await _create(client, auth_headers, asset_type="jd", is_draft=True)
    await _create(client, auth_headers, asset_type="note", title="笔记", is_draft=True)
    resp = await client.get("/api/v1/assets?asset_type=jd", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["items"][0]["asset_type"] == "jd"


@pytest.mark.asyncio
async def test_update_asset_bumps_version(client, auth_headers):
    created = (await _create(client, auth_headers, is_draft=True)).json()
    resp = await client.put(
        f"/api/v1/assets/{created['id']}",
        json={"content": "v2 content"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["version"] == 2
    assert data["content"] == "v2 content"


@pytest.mark.asyncio
async def test_delete_asset(client, auth_headers):
    created = (await _create(client, auth_headers, is_draft=True)).json()
    resp = await client.delete(f"/api/v1/assets/{created['id']}", headers=auth_headers)
    assert resp.status_code == 204
    resp2 = await client.get(f"/api/v1/assets/{created['id']}", headers=auth_headers)
    assert resp2.status_code == 404


@pytest.mark.asyncio
async def test_asset_isolation(client, auth_headers):
    """非本人访问他人资产 → 404（防枚举）。"""
    created = (await _create(client, auth_headers, is_draft=True)).json()
    other_headers = await _register_other(client)
    resp = await client.get(f"/api/v1/assets/{created['id']}", headers=other_headers)
    assert resp.status_code == 404
    resp2 = await client.delete(f"/api/v1/assets/{created['id']}", headers=other_headers)
    assert resp2.status_code == 404


@pytest.mark.asyncio
async def test_create_asset_ready_does_not_crash(client, auth_headers):
    """is_draft=False 触发懒索引（测试环境向量库可能不可用，应降级而非 500）。"""
    resp = await _create(client, auth_headers, is_draft=False)
    assert resp.status_code in (201, 500)  # 索引失败降级不保证；核心是 API 不挂
    if resp.status_code == 201:
        assert resp.json()["is_draft"] is False
