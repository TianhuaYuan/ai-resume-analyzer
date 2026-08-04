"""G 面试复盘 API 测试（/api/v1/interviews）。"""

import pytest


async def _create(client, headers, **overrides):
    body = {"company": "字节", "position": "后端开发"}
    body.update(overrides)
    return await client.post("/api/v1/interviews", json=body, headers=headers)


@pytest.mark.asyncio
async def test_create_interview(client, auth_headers):
    resp = await _create(
        client,
        auth_headers,
        questions=["讲一下你的项目"],
        answers=["独立设计并实现了..."],
        notes="一面通过",
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["company"] == "字节"
    assert data["position"] == "后端开发"
    assert data["status"] == "recorded"
    assert data["questions"] == ["讲一下你的项目"]


@pytest.mark.asyncio
async def test_create_interview_requires_company_position(client, auth_headers):
    resp = await client.post("/api/v1/interviews", json={}, headers=auth_headers)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_list_interviews(client, auth_headers):
    await _create(client, auth_headers, company="A公司")
    await _create(client, auth_headers, company="B公司")
    resp = await client.get("/api/v1/interviews", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["total"] == 2


@pytest.mark.asyncio
async def test_scorecard_update_returns_weak_competencies(client, auth_headers):
    created = (await _create(client, auth_headers)).json()
    scorecard = {"overall_score": 60, "competency_scores": [{"competency": "算法", "score": 50}]}
    resp = await client.put(
        f"/api/v1/interviews/{created['id']}/scorecard",
        json={"scorecard": scorecard},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "reviewed"
    assert "weak_competencies" in data


@pytest.mark.asyncio
async def test_review_summary(client, auth_headers):
    resp = await client.get("/api/v1/interviews/review/summary", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "frequent_weaknesses" in data
    assert "training_plan" in data
    assert "trend" in data


@pytest.mark.asyncio
async def test_delete_interview(client, auth_headers):
    created = (await _create(client, auth_headers)).json()
    resp = await client.delete(f"/api/v1/interviews/{created['id']}", headers=auth_headers)
    assert resp.status_code == 204
    resp2 = await client.get(f"/api/v1/interviews/{created['id']}", headers=auth_headers)
    assert resp2.status_code == 404


@pytest.mark.asyncio
async def test_interview_isolation(client, auth_headers):
    """非本人访问他人面试记录 → 404（防枚举，C4）。"""
    created = (await _create(client, auth_headers, company="私有公司")).json()
    # 注册第二个用户
    other = {"username": "otheriv", "email": "otheriv@example.com", "password": "Test1234!", "password_confirm": "Test1234!"}
    await client.post("/api/v1/auth/send-code", json={"email": other["email"]})
    from services.verification_service import _CODE_KEY_PREFIX, _in_memory_codes

    code = _in_memory_codes.get(f"{_CODE_KEY_PREFIX}{other['email']}")["code"]
    await client.post("/api/v1/auth/register", json={**other, "verification_code": code})
    login = await client.post("/api/v1/auth/login", json={"email": other["email"], "password": other["password"]})
    other_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    resp = await client.get(f"/api/v1/interviews/{created['id']}", headers=other_headers)
    assert resp.status_code == 404
    resp2 = await client.delete(f"/api/v1/interviews/{created['id']}", headers=other_headers)
    assert resp2.status_code == 404
