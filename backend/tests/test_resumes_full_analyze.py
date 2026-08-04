"""GET /api/v1/resumes/{id}/full-analyze 完整分析接口测试。

TDD 红：端点尚未实现，所有路由调用应返回 404。
TDD 绿：实现端点后所有用例通过。

接口行为：
- 返回一份简历的 4 种分析结果（summary/skills/experience/score）
- 优先批量读 Redis 缓存，全部命中时不调用 LLM
- 缓存缺失的类型自动调用 analyze_resume 补齐（同时写入缓存）
- 401 未登录 / 404 简历不存在或非本人 / 409 简历未就绪
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from httpx import AsyncClient

from models.resume import Resume
from tests.conftest import AsyncSessionTest


class _Msg:
    def __init__(self, text: str):
        self.content = text


class _Choice:
    def __init__(self, text: str):
        self.message = _Msg(text)


def _fake_chat_client(content: str):
    """构造 mock get_chat_client() 的客户端：chat.completions.create 返回指定文本。

    analyze_resume 走 get_chat_client() 而非 llm_generate，patch 目标需对齐：
    await client.chat.completions.create(model=..., messages=..., temperature=...)
    response.choices[0].message.content → analysis；usage=None 跳过 token 记账。
    """
    client = MagicMock()
    c = MagicMock()
    c.choices = [_Choice(content)]
    c.usage = None
    client.chat.completions.create = AsyncMock(return_value=c)
    return client


async def _insert_resume(
    user_id: int,
    *,
    status: str = "ready",
    parsed_text: str = "Python 后端工程师，3年 FastAPI 开发经验。",
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
async def test_full_analyze_without_auth(client: AsyncClient):
    """未登录 → 401。"""
    resp = await client.get("/api/v1/resumes/1/full-analyze")
    assert resp.status_code == 401


# ── 404 不存在 ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_full_analyze_nonexistent_resume(
    client: AsyncClient, auth_headers: dict
):
    """不存在的 resume_id → 404。"""
    resp = await client.get(
        "/api/v1/resumes/99999/full-analyze",
        headers=auth_headers,
    )
    assert resp.status_code == 404


# ── 409 简历未就绪 ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_full_analyze_processing_resume_returns_409(
    client: AsyncClient, auth_headers: dict, registered_user: dict
):
    """status == 'processing' → 409。"""
    resume_id = await _insert_resume(
        registered_user["id"], status="processing", parsed_text=""
    )
    resp = await client.get(
        f"/api/v1/resumes/{resume_id}/full-analyze",
        headers=auth_headers,
    )
    assert resp.status_code == 409


# ── 200 成功：返回 4 种分析结果 ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_full_analyze_returns_all_four_types(
    client: AsyncClient, auth_headers: dict, registered_user: dict
):
    """成功返回 summary/skills/experience/score 4 个字段。"""
    resume_id = await _insert_resume(registered_user["id"])

    with patch(
        "services.analyze_service.get_full_analysis_cache",
        AsyncMock(return_value=None),  # 强制走 LLM，避免共享缓存干扰
    ), patch(
        "services.analyze_service.get_analysis_cache",
        AsyncMock(return_value=None),
    ), patch(
        "services.analyze_service.get_chat_client",
        return_value=_fake_chat_client("分析结果文本"),
    ):
        resp = await client.get(
            f"/api/v1/resumes/{resume_id}/full-analyze",
            headers=auth_headers,
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["resume_id"] == resume_id
    # 4 种类型都应存在
    for analysis_type in ("summary", "skills", "experience", "score"):
        assert analysis_type in data, f"缺少字段: {analysis_type}"
        item = data[analysis_type]
        assert item["resume_id"] == resume_id
        assert item["analysis_type"] == analysis_type
        assert isinstance(item["analysis"], str)
        assert item["analysis"]  # 非空


@pytest.mark.asyncio
async def test_full_analyze_score_contains_scores_dict(
    client: AsyncClient, auth_headers: dict, registered_user: dict
):
    """score 类型应包含 scores 结构化评分（当 LLM 返回可解析格式时）。"""
    resume_id = await _insert_resume(registered_user["id"])

    # 模拟 LLM 返回带分数的评分文本
    score_text = (
        "## 综合评分\n\n"
        "### ATS 匹配率: 85/100\n结构清晰\n\n"
        "### 关键词覆盖率: 70/100\n关键词丰富\n\n"
        "### 技能密度: 80/100\n技能深入\n\n"
        "### 综合评价: 78/100\n综合表现良好\n"
    )
    with patch(
        "services.analyze_service.get_full_analysis_cache",
        AsyncMock(return_value=None),  # 强制走 LLM，避免共享缓存干扰
    ), patch(
        "services.analyze_service.get_analysis_cache",
        AsyncMock(return_value=None),
    ), patch(
        "services.analyze_service.get_chat_client",
        return_value=_fake_chat_client(score_text),
    ):
        resp = await client.get(
            f"/api/v1/resumes/{resume_id}/full-analyze",
            headers=auth_headers,
        )

    assert resp.status_code == 200
    score_field = resp.json()["score"]
    assert score_field["scores"] is not None
    assert score_field["scores"]["overall"] == 78
    assert score_field["scores"]["ats_match"] == 85


# ── 缓存命中优化 ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_full_analyze_uses_cache_when_all_hit(
    client: AsyncClient, auth_headers: dict, registered_user: dict
):
    """4 种类型缓存全部命中时不调用 LLM。"""
    resume_id = await _insert_resume(registered_user["id"])

    # 预置完整缓存
    fake_full_cache = {
        "summary": {
            "resume_id": resume_id,
            "analysis_type": "summary",
            "analysis": "缓存中的总结",
        },
        "skills": {
            "resume_id": resume_id,
            "analysis_type": "skills",
            "analysis": "缓存中的技能",
        },
        "experience": {
            "resume_id": resume_id,
            "analysis_type": "experience",
            "analysis": "缓存中的经历",
        },
        "score": {
            "resume_id": resume_id,
            "analysis_type": "score",
            "analysis": "缓存中的评分",
            "scores": {
                "ats_match": 90,
                "keyword_coverage": 85,
                "skill_density": 88,
                "overall": 87,
            },
        },
    }

    with patch(
        "services.analyze_service.get_full_analysis_cache",
        AsyncMock(return_value=fake_full_cache),
    ) as mock_get_cache, patch(
        "services.analyze_service.get_chat_client",
    ) as mock_get_chat:
        resp = await client.get(
            f"/api/v1/resumes/{resume_id}/full-analyze",
            headers=auth_headers,
        )

    assert resp.status_code == 200
    assert mock_get_cache.await_count == 1
    mock_get_chat.assert_not_called()  # 缓存全命中，不应调用 LLM

    data = resp.json()
    assert data["summary"]["analysis"] == "缓存中的总结"
    assert data["score"]["scores"]["overall"] == 87


@pytest.mark.asyncio
async def test_full_analyze_falls_back_to_llm_on_cache_miss(
    client: AsyncClient, auth_headers: dict, registered_user: dict
):
    """缓存未命中时调用 LLM 补齐，并写回缓存。"""
    resume_id = await _insert_resume(registered_user["id"])

    with patch(
        "services.analyze_service.get_full_analysis_cache",
        AsyncMock(return_value=None),  # 完整缓存未命中
    ), patch(
        "services.analyze_service.get_analysis_cache",
        AsyncMock(return_value=None),  # 单类型缓存也未命中（避免同文件前序测试写入的缓存干扰）
    ), patch(
        "services.analyze_service.get_chat_client",
        return_value=_fake_chat_client("LLM 生成的分析"),
    ) as mock_get_chat:
        resp = await client.get(
            f"/api/v1/resumes/{resume_id}/full-analyze",
            headers=auth_headers,
        )

    assert resp.status_code == 200
    # 4 种类型都未命中，应调用 4 次 get_chat_client（每次 analyze_resume 各一次）
    assert mock_get_chat.call_count == 4
    data = resp.json()
    for analysis_type in ("summary", "skills", "experience", "score"):
        assert data[analysis_type]["analysis"] == "LLM 生成的分析"
