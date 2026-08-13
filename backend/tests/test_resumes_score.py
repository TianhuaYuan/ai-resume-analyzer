"""POST /api/v1/resumes/{id}/analyze (type=score) 端点测试。

P1.1 新增 score 分析类型：
- LLM 返回 ATS 匹配率、关键词覆盖率、技能密度的量化评分
- AnalyzeResponse 新增 scores 可选字段

覆盖：
- 200 score 类型成功（mock llm_generate 返回 JSON 评分）
- 200 score 返回的 analysis 包含量化评分
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

# ## ATS 匹配率: 75/100
简历结构清晰，关键词匹配度较好，但缺少部分 ATS 友好的格式元素。

# ## 关键词覆盖率: 68/100
覆盖核心后端技能（Python/FastAPI/MySQL），但缺少 DevOps（Kubernetes/CI/CD）和云服务（AWS/阿里云）关键词。

# ## 技能密度: 72/100
技能描述较为集中，建议扩展到版本控制（Git）、消息队列（RabbitMQ/Kafka）等领域。

# ## 综合评价: 72/100
简历定位明确，核心技能匹配度高，但在 DevOps 和云服务方面存在提升空间。
"""


@pytest.mark.asyncio
async def test_analyze_score_success(
    client: AsyncClient, auth_headers: dict, registered_user: dict
):
    """score 类型成功 → 200 + 量化评分。"""
    resume_id = await _insert_resume(registered_user["id"])
    with patch(
        "services.analyze_service.get_analysis_cache",
        AsyncMock(return_value=None),  # 强制走 LLM，避免共享缓存干扰
    ), patch(
        "services.analyze_service.get_chat_client",
        return_value=_fake_chat_client(_MOCK_SCORE_ANALYSIS),
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
        "services.analyze_service.get_analysis_cache",
        AsyncMock(return_value=None),  # 强制走 LLM，避免共享缓存干扰
    ), patch(
        "services.analyze_service.get_chat_client",
        return_value=_fake_chat_client(_MOCK_SCORE_ANALYSIS),
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
        "services.analyze_service.get_analysis_cache",
        AsyncMock(return_value=None),  # 强制走 LLM，避免共享缓存干扰
    ), patch(
        "services.analyze_service.get_chat_client",
        return_value=_fake_chat_client("候选人精通 Python。"),
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


# ── Task 2.5: _parse_scores 多格式提取单元测试 ──

from services.analyze_service import _parse_scores  # noqa: E402


class TestParseScoresFormats:
    """Task 2.5: _parse_scores 应支持多种 LLM 输出格式。"""

    def test_format_xx_slash_100(self):
        """格式1: 'XX/100'（原始格式）。"""
        text = (
            "### ATS 匹配率: 75/100\n"
            "### 关键词覆盖率: 68/100\n"
            "### 技能密度: 72/100\n"
            "### 综合评价: 70/100\n"
        )
        scores = _parse_scores(text)
        assert scores is not None
        assert scores.ats_match == 75
        assert scores.keyword_coverage == 68
        assert scores.skill_density == 72
        assert scores.overall == 70

    def test_format_xx_fen(self):
        """格式2: 'XX分'。"""
        text = (
            "ATS 匹配率: 75分\n"
            "关键词覆盖率: 68分\n"
            "技能密度: 72分\n"
            "综合评价: 70分\n"
        )
        scores = _parse_scores(text)
        assert scores is not None
        assert scores.ats_match == 75
        assert scores.keyword_coverage == 68
        assert scores.skill_density == 72
        assert scores.overall == 70

    def test_format_score_colon_xx(self):
        """格式3: 'score: XX'（英文键值）。"""
        text = (
            "ATS score: 75\n"
            "keyword score: 68\n"
            "skill score: 72\n"
            "overall score: 70\n"
        )
        scores = _parse_scores(text)
        assert scores is not None
        assert scores.ats_match == 75
        assert scores.keyword_coverage == 68
        assert scores.skill_density == 72
        assert scores.overall == 70

    def test_format_xx_slash_100_fen(self):
        """格式4: 'XX/100分'（混合）。"""
        text = (
            "ATS 匹配率: 75/100分\n"
            "关键词覆盖率: 68/100分\n"
            "技能密度: 72/100分\n"
            "综合评价: 70/100分\n"
        )
        scores = _parse_scores(text)
        assert scores is not None
        assert scores.ats_match == 75
        assert scores.keyword_coverage == 68
        assert scores.skill_density == 72
        assert scores.overall == 70

    def test_format_de_fen_xx(self):
        """格式5: '得分: XX'（中文键值）。"""
        text = (
            "ATS 得分: 75\n"
            "关键词 得分: 68\n"
            "技能 得分: 72\n"
            "综合 得分: 70\n"
        )
        scores = _parse_scores(text)
        assert scores is not None
        assert scores.ats_match == 75
        assert scores.keyword_coverage == 68
        assert scores.skill_density == 72
        assert scores.overall == 70

    def test_format_mixed(self):
        """格式6: 混合多种格式（LLM 实际常见）。"""
        text = (
            "## ATS 匹配率\n75/100\n"
            "## 关键词覆盖率\n68分\n"
            "## 技能密度\nscore: 72\n"
            "## 综合评价\n得分: 70\n"
        )
        scores = _parse_scores(text)
        assert scores is not None
        assert scores.ats_match == 75
        assert scores.keyword_coverage == 68
        assert scores.skill_density == 72
        assert scores.overall == 70

    def test_insufficient_scores_returns_none(self):
        """分数不足 4 个 → None。"""
        text = "ATS 匹配率: 75/100\n关键词覆盖率: 68/100\n技能密度: 72/100"
        assert _parse_scores(text) is None

    def test_score_out_of_range_returns_none(self):
        """分数 > 100 → None（避免误匹配年份、ID 等）。"""
        text = (
            "ATS 匹配率: 75/100\n"
            "关键词覆盖率: 68/100\n"
            "技能密度: 72/100\n"
            "综合评价: 2024/100\n"  # 2024 不是合法分数
        )
        # 2024 > 100 应被过滤，导致有效分数不足 4 个
        scores = _parse_scores(text)
        # 期望 None 或仅取前 3 个合法分数 + 没有 4th → None
        assert scores is None

    def test_empty_text_returns_none(self):
        """空文本 → None。"""
        assert _parse_scores("") is None

    def test_no_numeric_scores_returns_none(self):
        """纯文字描述无数字 → None。"""
        text = "简历结构清晰，关键词匹配度较好，但缺少部分 ATS 友好的格式元素。"
        assert _parse_scores(text) is None

    def test_scores_exactly_four_uses_order(self):
        """4 个分数按出现顺序对应 ATS/关键词/技能密度/综合。"""
        text = "85/100\n90/100\n78/100\n82/100\n"
        scores = _parse_scores(text)
        assert scores is not None
        assert scores.ats_match == 85
        assert scores.keyword_coverage == 90
        assert scores.skill_density == 78
        assert scores.overall == 82

    def test_scores_extra_numbers_takes_first_four(self):
        """超过 4 个数字时取前 4 个（避免被无关数字污染）。"""
        text = (
            "### ATS 匹配率: 75/100\n"
            "### 关键词覆盖率: 68/100\n"
            "### 技能密度: 72/100\n"
            "### 综合评价: 70/100\n"
            "备注: 简历编号 12345，年份 2024\n"
        )
        scores = _parse_scores(text)
        assert scores is not None
        assert scores.ats_match == 75
        assert scores.keyword_coverage == 68
        assert scores.skill_density == 72
        assert scores.overall == 70


# ── Task 2.5: 端到端 - LLM 输出非标准格式时仍能提取分数 ──


@pytest.mark.asyncio
async def test_analyze_score_with_fen_format_extracts_scores(
    client: AsyncClient, auth_headers: dict, registered_user: dict
):
    """LLM 返回 'XX分' 格式时应能提取 scores。"""
    resume_id = await _insert_resume(registered_user["id"])
    fen_analysis = (
        "## 综合评分\n\n"
        "### ATS 匹配率: 80分\n结构清晰。\n\n"
        "### 关键词覆盖率: 70分\n覆盖核心技能。\n\n"
        "### 技能密度: 75分\n技能描述集中。\n\n"
        "### 综合评价: 78分\n定位明确。\n"
    )
    with patch(
        "services.analyze_service.get_analysis_cache",
        AsyncMock(return_value=None),  # 强制走 LLM，避免共享缓存干扰
    ), patch(
        "services.analyze_service.get_chat_client",
        return_value=_fake_chat_client(fen_analysis),
    ):
        resp = await client.post(
            f"/api/v1/resumes/{resume_id}/analyze",
            json={"analysis_type": "score"},
            headers=auth_headers,
        )
    assert resp.status_code == 200
    data = resp.json()
    assert "scores" in data
    assert data["scores"]["ats_match"] == 80
    assert data["scores"]["keyword_coverage"] == 70
    assert data["scores"]["skill_density"] == 75
    assert data["scores"]["overall"] == 78


@pytest.mark.asyncio
async def test_analyze_score_unparseable_omits_scores_field(
    client: AsyncClient, auth_headers: dict, registered_user: dict
):
    """LLM 输出无法提取分数时，result 不含 scores 字段（前端独立 fallback）。"""
    resume_id = await _insert_resume(registered_user["id"])
    unparseable = (
        "该简历整体表现良好，结构清晰，技能匹配度高。"
        "建议在 DevOps 方向补充经验。"
    )
    with patch(
        "services.analyze_service.get_analysis_cache",
        AsyncMock(return_value=None),  # 强制走 LLM，避免共享缓存干扰
    ), patch(
        "services.analyze_service.get_chat_client",
        return_value=_fake_chat_client(unparseable),
    ):
        resp = await client.post(
            f"/api/v1/resumes/{resume_id}/analyze",
            json={"analysis_type": "score"},
            headers=auth_headers,
        )
    assert resp.status_code == 200
    data = resp.json()
    # scores 字段应不存在或为 None
    assert data.get("scores") is None or "scores" not in data
    # analysis 文本仍正常返回（不被污染）
    assert "DevOps" in data["analysis"]
