"""POST /api/v1/resumes/{id}/analyze (type=score) 端点测试。

P1.1 新增 score 分析类型：
- LLM 返回 ATS 匹配率、关键词覆盖率、技能密度的量化评分
- AnalyzeResponse 新增 scores 可选字段

覆盖：
- 200 score 类型成功（mock llm_generate 返回 JSON 评分）
- 200 score 返回的 analysis 包含量化评分
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
    parsed_text: str = "Python 后端工程师，3年 FastAPI 开发经验。熟悉 LangChain、Docker、MySQL。",
) -> int:
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


_MOCK_SCORE_ANALYSIS = """## 综合评分

### ATS 匹配率: 75/100
简历结构清晰，关键词匹配度较好，但缺少部分 ATS 友好的格式元素。

### 关键词覆盖率: 68/100
覆盖核心后端技能（Python/FastAPI/MySQL），但缺少 DevOps（Kubernetes/CI/CD）和云服务（AWS/阿里云）关键词。

### 技能密度: 72/100
技能描述较为集中，建议扩展到版本控制（Git）、消息队列（RabbitMQ/Kafka）等领域。

### 综合评价: 72/100
简历定位明确，核心技能匹配度高，但在 DevOps 和云服务方面存在提升空间。
"""


@pytest.mark.asyncio
async def test_analyze_score_success(
    client: AsyncClient, auth_headers: dict, registered_user: dict
):
    """score 类型成功 → 200 + 量化评分。"""
    resume_id = await _insert_resume(registered_user["id"])
    with patch(
        "services.analyze_service.llm_generate",
        new_callable=AsyncMock,
        return_value=_MOCK_SCORE_ANALYSIS,
    ):
        resp = await client.post(
            f"/api/v1/resumes/{resume_id}/analyze",
            json={"analysis_type": "score"},
            headers=auth_headers,
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["resume_id"] == resume_id
    assert data["analysis_type"] == "score"
    assert "ATS" in data["analysis"]
    assert "75" in data["analysis"]


@pytest.mark.asyncio
async def test_analyze_score_returns_scores_field(
    client: AsyncClient, auth_headers: dict, registered_user: dict
):
    """score 类型应返回 scores 量化字段。"""
    resume_id = await _insert_resume(registered_user["id"])
    with patch(
        "services.analyze_service.llm_generate",
        new_callable=AsyncMock,
        return_value=_MOCK_SCORE_ANALYSIS,
    ):
        resp = await client.post(
            f"/api/v1/resumes/{resume_id}/analyze",
            json={"analysis_type": "score"},
            headers=auth_headers,
        )
    assert resp.status_code == 200
    data = resp.json()
    # scores 字段应存在
    assert "scores" in data
    scores = data["scores"]
    assert scores["ats_match"] == 75
    assert scores["keyword_coverage"] == 68
    assert scores["skill_density"] == 72
    assert scores["overall"] == 72


@pytest.mark.asyncio
async def test_analyze_non_score_types_no_scores_field(
    client: AsyncClient, auth_headers: dict, registered_user: dict
):
    """summary/skills/experience 类型不应返回 scores 字段。"""
    resume_id = await _insert_resume(registered_user["id"])
    with patch(
        "services.analyze_service.llm_generate",
        new_callable=AsyncMock,
        return_value="候选人精通 Python。",
    ):
        resp = await client.post(
            f"/api/v1/resumes/{resume_id}/analyze",
            json={"analysis_type": "summary"},
            headers=auth_headers,
        )
    assert resp.status_code == 200
    data = resp.json()
    # 非 score 类型，scores 应为 None 或不存在
    assert data.get("scores") is None or "scores" not in data
