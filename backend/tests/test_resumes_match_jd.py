"""POST /api/v1/resumes/{id}/match-jd 端点测试。

覆盖：
- 401 未登录
- 404 简历不存在或非本人
- 409 简历未就绪
- 422 JD 文本为空
- 200 成功匹配，返回 match_score / matching_points / gap_analysis / suggestions

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
    parsed_text: str = "Python 后端工程师，3年 FastAPI 开发经验，熟悉 Docker 和 CI/CD。",
    status: str = "ready",
) -> int:
    """直接插入 Resume 记录，返回 id。"""
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
async def test_match_jd_without_auth(client: AsyncClient):
    """未登录调用 JD 匹配 → 401。"""
    resp = await client.post(
        "/api/v1/resumes/1/match-jd",
        json={"jd_text": "Python 后端工程师"},
    )
    assert resp.status_code == 401


# ── 404 不存在 ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_match_jd_nonexistent_resume(client: AsyncClient, auth_headers: dict):
    """匹配不存在的 resume_id → 404。"""
    resp = await client.post(
        "/api/v1/resumes/99999/match-jd",
        json={"jd_text": "Python 后端工程师"},
        headers=auth_headers,
    )
    assert resp.status_code == 404


# ── 409 简历未就绪 ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_match_jd_processing_resume_returns_409(
    client: AsyncClient, auth_headers: dict, registered_user: dict
):
    """status == 'processing' → 409。"""
    resume_id = await _insert_resume(registered_user["id"], status="processing", parsed_text="")
    resp = await client.post(
        f"/api/v1/resumes/{resume_id}/match-jd",
        json={"jd_text": "Python 后端工程师"},
        headers=auth_headers,
    )
    assert resp.status_code == 409


# ── 422 JD 文本为空 ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_match_jd_empty_text_returns_422(
    client: AsyncClient, auth_headers: dict, registered_user: dict
):
    """JD 文本为空字符串 → 422。"""
    resume_id = await _insert_resume(registered_user["id"])
    resp = await client.post(
        f"/api/v1/resumes/{resume_id}/match-jd",
        json={"jd_text": ""},
        headers=auth_headers,
    )
    assert resp.status_code == 422


# ── 200 成功匹配 ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_match_jd_success(
    client: AsyncClient, auth_headers: dict, registered_user: dict
):
    """成功匹配 → 200，返回 match_score / matching_points / gap_analysis / suggestions。"""
    resume_id = await _insert_resume(registered_user["id"])

    mock_response = (
        "## 匹配分数\n85/100\n\n"
        "## 匹配点\n1. Python 开发经验匹配\n2. FastAPI 框架经验匹配\n\n"
        "## 差距分析\n1. 缺少 Kubernetes 经验\n2. 缺少微服务架构经验\n\n"
        "## 改进建议\n建议补充容器编排和服务治理相关经验。"
    )
    with patch(
        "services.match_jd_service.llm_generate",
        new_callable=AsyncMock,
        return_value=mock_response,
    ):
        resp = await client.post(
            f"/api/v1/resumes/{resume_id}/match-jd",
            json={"jd_text": "Python 后端工程师，要求熟悉 Kubernetes 和微服务架构。"},
            headers=auth_headers,
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["resume_id"] == resume_id
    assert "analysis" in data
    assert "85" in data["analysis"]


@pytest.mark.asyncio
async def test_match_jd_llm_failure_returns_500(
    client: AsyncClient, auth_headers: dict, registered_user: dict
):
    """LLM 调用失败（with_retry 无 fallback 时抛出）→ 500。"""
    resume_id = await _insert_resume(registered_user["id"])
    with patch(
        "services.match_jd_service.with_retry",
        new_callable=AsyncMock,
        side_effect=Exception("LLM 不可用"),
    ):
        resp = await client.post(
            f"/api/v1/resumes/{resume_id}/match-jd",
            json={"jd_text": "Python 后端工程师"},
            headers=auth_headers,
        )
    assert resp.status_code == 500
