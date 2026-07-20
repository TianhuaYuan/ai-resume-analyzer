"""POST /api/v1/resumes/{id}/analyze 端点测试。

覆盖：
- 401 未登录
- 404 简历不存在或非本人
- 409 简历未就绪（status != ready）
- 422 非法 analysis_type（Pydantic Literal 在 schema 层拦截）
- 200 summary / skills / experience 三种类型成功（mock llm_generate）

TDD 红：端点尚未实现，所有路由调用应返回 404。
TDD 绿：实现端点后所有用例通过。
"""

from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from models.resume import Resume
from tests.conftest import AsyncSessionTest


async def _insert_resume(
    user_id: int,
    *,
    status: str = "ready",
    parsed_text: str = "Python 后端工程师，3年 FastAPI 开发经验。",
) -> int:
    """直接插入 Resume 记录，返回 id。绕过上传/解析流程。"""
    async with AsyncSessionTest() as session:
        resume = Resume(
            user_id=user_id,
            filename="test.pdf",
            file_path="/tmp/test.pdf",
            parsed_text=parsed_text,
            status=status,
        )
        session.add(resume)
        await session.commit()
        await session.refresh(resume)
        return resume.id


# ── 认证校验 ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_analyze_without_auth(client: AsyncClient):
    """未登录调用分析 → 401。"""
    resp = await client.post(
        "/api/v1/resumes/1/analyze",
        json={"analysis_type": "summary"},
    )
    assert resp.status_code == 401


# ── 404 不存在 ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_analyze_nonexistent_resume(client: AsyncClient, auth_headers: dict):
    """分析不存在的 resume_id → 404。"""
    resp = await client.post(
        "/api/v1/resumes/99999/analyze",
        json={"analysis_type": "summary"},
        headers=auth_headers,
    )
    assert resp.status_code == 404


# ── 409 简历未就绪 ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_analyze_processing_resume_returns_409(
    client: AsyncClient, auth_headers: dict, registered_user: dict
):
    """status == 'processing' → 409。"""
    resume_id = await _insert_resume(registered_user["id"], status="processing", parsed_text="")
    resp = await client.post(
        f"/api/v1/resumes/{resume_id}/analyze",
        json={"analysis_type": "summary"},
        headers=auth_headers,
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_analyze_failed_resume_returns_409(
    client: AsyncClient, auth_headers: dict, registered_user: dict
):
    """status == 'failed' → 409。"""
    resume_id = await _insert_resume(registered_user["id"], status="failed", parsed_text="")
    resp = await client.post(
        f"/api/v1/resumes/{resume_id}/analyze",
        json={"analysis_type": "summary"},
        headers=auth_headers,
    )
    assert resp.status_code == 409


# ── 422 非法 analysis_type ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_analyze_invalid_type_returns_422(
    client: AsyncClient, auth_headers: dict, registered_user: dict
):
    """非法 analysis_type → 422（Pydantic Literal 在 schema 层拦截）。"""
    resume_id = await _insert_resume(registered_user["id"])
    resp = await client.post(
        f"/api/v1/resumes/{resume_id}/analyze",
        json={"analysis_type": "invalid_type"},
        headers=auth_headers,
    )
    assert resp.status_code == 422


# ── 200 成功 - 三种分析类型 ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_analyze_summary_success(
    client: AsyncClient, auth_headers: dict, registered_user: dict
):
    """summary 类型成功 → 200 + 分析内容。"""
    resume_id = await _insert_resume(registered_user["id"])
    with patch(
        "services.analyze_service.llm_generate",
        new_callable=AsyncMock,
        return_value="候选人精通 Python 与 FastAPI，有 3 年后端开发经验。",
    ):
        resp = await client.post(
            f"/api/v1/resumes/{resume_id}/analyze",
            json={"analysis_type": "summary"},
            headers=auth_headers,
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["resume_id"] == resume_id
    assert data["analysis_type"] == "summary"
    assert "Python" in data["analysis"]


@pytest.mark.asyncio
async def test_analyze_skills_success(
    client: AsyncClient, auth_headers: dict, registered_user: dict
):
    """skills 类型成功 → 200。"""
    resume_id = await _insert_resume(registered_user["id"])
    with patch(
        "services.analyze_service.llm_generate",
        new_callable=AsyncMock,
        return_value="编程语言: Python\n框架: FastAPI, LangChain",
    ):
        resp = await client.post(
            f"/api/v1/resumes/{resume_id}/analyze",
            json={"analysis_type": "skills"},
            headers=auth_headers,
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["resume_id"] == resume_id
    assert data["analysis_type"] == "skills"
    assert "Python" in data["analysis"]


@pytest.mark.asyncio
async def test_analyze_experience_success(
    client: AsyncClient, auth_headers: dict, registered_user: dict
):
    """experience 类型成功 → 200。"""
    resume_id = await _insert_resume(registered_user["id"])
    with patch(
        "services.analyze_service.llm_generate",
        new_callable=AsyncMock,
        return_value="工作经历:\n- A 公司 后端工程师 2022-2024",
    ):
        resp = await client.post(
            f"/api/v1/resumes/{resume_id}/analyze",
            json={"analysis_type": "experience"},
            headers=auth_headers,
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["resume_id"] == resume_id
    assert data["analysis_type"] == "experience"
    assert "A 公司" in data["analysis"]
