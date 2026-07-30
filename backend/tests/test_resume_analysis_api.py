"""
简历后台分析 API 测试：analysis-status + analyze-background。

TDD: 这些测试应先失败，因为对应 API 尚未实现。
"""

import pytest
from httpx import AsyncClient

from models.resume import Resume
from tests.conftest import AsyncSessionTest


async def _insert_resume(
    user_id: int,
    *,
    status: str = "ready",
) -> int:
    """直接插入 Resume 记录，返回 id。"""
    async with AsyncSessionTest() as session:
        resume = Resume(
            user_id=user_id,
            filename="test.pdf",
            file_path="/tmp/test.pdf",
            parsed_text="Python 后端工程师，3年 FastAPI 开发经验。",
            status=status,
        )
        session.add(resume)
        await session.commit()
        await session.refresh(resume)
        return resume.id


# ── GET /analysis-status ──────────────────────────────────


@pytest.mark.asyncio
async def test_analysis_status_without_auth(client: AsyncClient):
    """未登录访问 analysis-status → 401。"""
    resp = await client.get("/api/v1/resumes/1/analysis-status")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_analysis_status_not_found(
    client: AsyncClient, auth_headers: dict
):
    """不存在的简历 → 404。"""
    resp = await client.get(
        "/api/v1/resumes/999/analysis-status", headers=auth_headers
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_analysis_status_not_ready(
    client: AsyncClient, registered_user: dict, auth_headers: dict
):
    """简历未就绪（processing）→ 409。"""
    resume_id = await _insert_resume(registered_user["id"], status="processing")
    resp = await client.get(
        f"/api/v1/resumes/{resume_id}/analysis-status",
        headers=auth_headers,
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_analysis_status_ready_no_cache(
    client: AsyncClient, registered_user: dict, auth_headers: dict
):
    """简历就绪但无分析缓存 → {has_cache: false, cached_types: []}。"""
    resume_id = await _insert_resume(registered_user["id"], status="ready")
    resp = await client.get(
        f"/api/v1/resumes/{resume_id}/analysis-status",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["has_cache"] is False
    assert data["cached_types"] == []


# ── POST /analyze-background ──────────────────────────────


@pytest.mark.asyncio
async def test_analyze_background_without_auth(client: AsyncClient):
    """未登录访问 analyze-background → 401。"""
    resp = await client.post("/api/v1/resumes/1/analyze-background")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_analyze_background_not_found(
    client: AsyncClient, auth_headers: dict
):
    """不存在的简历 → 404。"""
    resp = await client.post(
        "/api/v1/resumes/999/analyze-background", headers=auth_headers
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_analyze_background_not_ready(
    client: AsyncClient, registered_user: dict, auth_headers: dict
):
    """简历未就绪（processing）→ 409。"""
    resume_id = await _insert_resume(registered_user["id"], status="processing")
    resp = await client.post(
        f"/api/v1/resumes/{resume_id}/analyze-background",
        headers=auth_headers,
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_analyze_background_accepts(
    client: AsyncClient, registered_user: dict, auth_headers: dict
):
    """简历就绪 → 202 accepted + 任务已加入队列消息。"""
    resume_id = await _insert_resume(registered_user["id"], status="ready")
    resp = await client.post(
        f"/api/v1/resumes/{resume_id}/analyze-background",
        headers=auth_headers,
    )
    assert resp.status_code == 202
    data = resp.json()
    assert data["status"] == "accepted"
    assert "resume_id" in data


@pytest.mark.asyncio
async def test_analyze_background_owned_by_other(
    client: AsyncClient, registered_user: dict, auth_headers: dict
):
    """尝试分析他人简历 → 404（归属校验）。"""
    # 用第一个用户插入数据，用第二个用户的 headers 访问
    other_id = await _insert_resume(registered_user["id"], status="ready")
    # 注册另一个用户
    resp2 = await client.post(
        "/api/v1/auth/send-code", json={"email": "other@example.com"}
    )
    assert resp2.status_code == 200
    from services.verification_service import _in_memory_codes, _CODE_KEY_PREFIX
    code_key = f"{_CODE_KEY_PREFIX}other@example.com"
    code_entry = _in_memory_codes.get(code_key)
    verification_code = code_entry["code"] if code_entry else "123456"
    await client.post("/api/v1/auth/register", json={
        "username": "otheruser",
        "email": "other@example.com",
        "password": "Test1234!",
        "password_confirm": "Test1234!",
        "verification_code": verification_code,
    })
    resp3 = await client.post("/api/v1/auth/login", json={
        "email": "other@example.com",
        "password": "Test1234!",
    })
    token = resp3.json()["access_token"]
    other_headers = {"Authorization": f"Bearer {token}"}

    resp = await client.post(
        f"/api/v1/resumes/{other_id}/analyze-background",
        headers=other_headers,
    )
    assert resp.status_code == 404
