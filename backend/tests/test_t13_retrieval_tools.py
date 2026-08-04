"""T13: 检索/包装工具 — search_resume / jd_match / diagnose_resume / compare_resumes。

测试范围：
- SearchResumeTool: 调 hybrid_search + rerank，返回 top5 格式化结果
- JDMatchTool: 包装 match_jd 服务，返回分析文本
- DiagnoseResumeTool: 调 analyze_resume(experience + score)，返回综合诊断
- CompareResumesTool: 包装 compare_resumes 服务，返回对比结果
- 错误处理（简历不存在 / 服务异常）
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from services.react_agent.tools import (
    SearchResumeTool,
    JDMatchTool,
    DiagnoseResumeTool,
    CompareResumesTool,
)


# ── 辅助函数 ──────────────────────────────────────────────────


def _make_mock_db(resume_status: str | None = "ready"):
    """通用 mock db：execute/get 返回同步 result。

    不能用裸 AsyncMock —— 其 scalar_one_or_none()/get() 是 coroutine，
    _get_resume / ensure_indexed 访问结果会报 'coroutine' object has no attribute 'status'。
    """
    db = MagicMock()
    resume = None
    if resume_status is not None:
        resume = MagicMock()
        resume.id = 1
        resume.status = resume_status
        resume.filename = "test.pdf"
        resume.file_path = "/uploads/test.pdf"
        resume.parsed_text = "内容"
    result = MagicMock()
    result.scalar_one_or_none.return_value = resume
    db.execute = AsyncMock(return_value=result)
    db.get = AsyncMock(return_value=resume)
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    return db


def _make_chunk(text=" chunk text", section="项目经验", score=0.85, chunk_index=0):
    """构造一个检索结果 chunk。"""
    return {
        "text": text,
        "section": section,
        "score": score,
        "chunk_index": chunk_index,
        "source": "dense",
    }


# ═══════════════════════════════════════════════════════════════
# SearchResumeTool
# ═══════════════════════════════════════════════════════════════


class TestSearchResumeTool:
    """简历内容检索。"""

    @pytest.mark.asyncio
    async def test_returns_formatted_results(self):
        """返回格式化的检索结果。"""
        tool = SearchResumeTool(db=_make_mock_db(), user_id=1)
        chunks = [_make_chunk(text="Python后端开发经验", section="工作经历"),
                  _make_chunk(text="FastAPI项目", section="项目经验", chunk_index=1)]

        with patch("services.react_agent.tools.hybrid_search", new_callable=AsyncMock) as mock_search, \
             patch("services.react_agent.tools.ensure_indexed", new_callable=AsyncMock), \
             patch("services.react_agent.tools.rerank", new_callable=AsyncMock) as mock_rerank:
            mock_search.return_value = chunks
            mock_rerank.return_value = chunks

            result = await tool._execute(resume_id=1, query="Python经验")

        assert "Python后端开发经验" in result
        assert "FastAPI项目" in result

    @pytest.mark.asyncio
    async def test_passes_query_to_hybrid_search(self):
        """query 传递到 hybrid_search。"""
        tool = SearchResumeTool(db=_make_mock_db(), user_id=1)

        with patch("services.react_agent.tools.hybrid_search", new_callable=AsyncMock) as mock_search, \
             patch("services.react_agent.tools.ensure_indexed", new_callable=AsyncMock), \
             patch("services.react_agent.tools.rerank", new_callable=AsyncMock) as mock_rerank:
            mock_search.return_value = []
            mock_rerank.return_value = []

            await tool._execute(resume_id=1, query="我的项目经历")

            call_args = mock_search.call_args
            assert "项目经历" in str(call_args)

    @pytest.mark.asyncio
    async def test_passes_resume_id_to_hybrid_search(self):
        """resume_id 传递到 hybrid_search。"""
        tool = SearchResumeTool(db=_make_mock_db(), user_id=1)

        with patch("services.react_agent.tools.hybrid_search", new_callable=AsyncMock) as mock_search, \
             patch("services.react_agent.tools.ensure_indexed", new_callable=AsyncMock), \
             patch("services.react_agent.tools.rerank", new_callable=AsyncMock) as mock_rerank:
            mock_search.return_value = []
            mock_rerank.return_value = []

            await tool._execute(resume_id=42, query="技能")

            call_args = mock_search.call_args
            # hybrid_search(user_id, resume_id, query, top_k=20) — resume_id 是第 2 个位置参数
            assert call_args.args[1] == 42 or call_args.kwargs.get("resume_id") == 42

    @pytest.mark.asyncio
    async def test_handles_no_results(self):
        """无检索结果时返回提示。"""
        tool = SearchResumeTool(db=_make_mock_db(), user_id=1)

        with patch("services.react_agent.tools.hybrid_search", new_callable=AsyncMock) as mock_search, \
             patch("services.react_agent.tools.ensure_indexed", new_callable=AsyncMock), \
             patch("services.react_agent.tools.rerank", new_callable=AsyncMock) as mock_rerank:
            mock_search.return_value = []
            mock_rerank.return_value = []

            result = await tool._execute(resume_id=1, query="不相关的内容")

        assert "未找到" in result or "无相关" in result or "未提及" in result

    @pytest.mark.asyncio
    async def test_result_includes_section_info(self):
        """结果包含分节信息。"""
        tool = SearchResumeTool(db=_make_mock_db(), user_id=1)
        chunks = [_make_chunk(text="内容A", section="工作经历")]

        with patch("services.react_agent.tools.hybrid_search", new_callable=AsyncMock) as mock_search, \
             patch("services.react_agent.tools.ensure_indexed", new_callable=AsyncMock), \
             patch("services.react_agent.tools.rerank", new_callable=AsyncMock) as mock_rerank:
            mock_search.return_value = chunks
            mock_rerank.return_value = chunks

            result = await tool._execute(resume_id=1, query="工作")

        assert "工作经历" in result


# ═══════════════════════════════════════════════════════════════
# JDMatchTool
# ═══════════════════════════════════════════════════════════════


class TestJDMatchTool:
    """简历与 JD 匹配分析。"""

    @pytest.mark.asyncio
    async def test_returns_analysis(self):
        """返回 JD 匹配分析结果。"""
        tool = JDMatchTool(db=_make_mock_db(), user_id=1)

        with patch("services.react_agent.tools.match_jd", new_callable=AsyncMock) as mock_match:
            mock_match.return_value = {"resume_id": 1, "analysis": "匹配度 85%，主要匹配点..."}

            result = await tool._execute(resume_id=1, jd_text="Python后端，3年经验")

        assert "匹配度 85%" in result

    @pytest.mark.asyncio
    async def test_passes_jd_text(self):
        """jd_text 传递到 match_jd。"""
        tool = JDMatchTool(db=_make_mock_db(), user_id=1)

        with patch("services.react_agent.tools.match_jd", new_callable=AsyncMock) as mock_match:
            mock_match.return_value = {"resume_id": 1, "analysis": "result"}

            await tool._execute(resume_id=1, jd_text="需要熟悉 Kubernetes 和 Docker")

            call_args = mock_match.call_args
            # jd_text 应该在位置参数或 kwargs 中
            all_args = str(call_args.args) + str(call_args.kwargs)
            assert "Kubernetes" in all_args

    @pytest.mark.asyncio
    async def test_passes_resume_id(self):
        """resume_id 传递到 match_jd。"""
        tool = JDMatchTool(db=_make_mock_db(), user_id=1)

        with patch("services.react_agent.tools.match_jd", new_callable=AsyncMock) as mock_match:
            mock_match.return_value = {"resume_id": 1, "analysis": "result"}

            await tool._execute(resume_id=99, jd_text="岗位描述")

            call_args = mock_match.call_args
            assert 99 in call_args.args or call_args.kwargs.get("resume_id") == 99

    @pytest.mark.asyncio
    async def test_handles_resume_not_found(self):
        """简历不存在时返回提示。"""
        tool = JDMatchTool(db=_make_mock_db(), user_id=1)

        with patch("services.react_agent.tools.match_jd", new_callable=AsyncMock) as mock_match:
            mock_match.side_effect = HTTPException(status_code=404, detail="简历不存在")

            result = await tool._execute(resume_id=999, jd_text="岗位")

        assert "不存在" in result or "找不到" in result or "无法" in result

    @pytest.mark.asyncio
    async def test_handles_resume_not_ready(self):
        """简历未就绪时返回提示。"""
        tool = JDMatchTool(db=_make_mock_db(), user_id=1)

        with patch("services.react_agent.tools.match_jd", new_callable=AsyncMock) as mock_match:
            mock_match.side_effect = HTTPException(status_code=409, detail="简历未就绪")

            result = await tool._execute(resume_id=1, jd_text="岗位")

        assert "未就绪" in result or "处理中" in result or "无法" in result


# ═══════════════════════════════════════════════════════════════
# DiagnoseResumeTool
# ═══════════════════════════════════════════════════════════════


class TestDiagnoseResumeTool:
    """简历诊断。"""

    @pytest.mark.asyncio
    async def test_returns_diagnosis(self):
        """返回诊断结果。"""
        tool = DiagnoseResumeTool(db=_make_mock_db(), user_id=1)

        with patch("services.react_agent.tools.analyze_resume", new_callable=AsyncMock) as mock_analyze:
            mock_analyze.side_effect = [
                {"resume_id": 1, "analysis_type": "experience", "analysis": "工作经历分析结果"},
                {"resume_id": 1, "analysis_type": "score", "analysis": "评分: 75分", "scores": {"overall": 75}},
            ]

            result = await tool._execute(resume_id=1)

        assert "工作经历分析结果" in result
        assert "评分" in result or "75" in result

    @pytest.mark.asyncio
    async def test_calls_experience_and_score(self):
        """调用 experience 和 score 两种分析。"""
        tool = DiagnoseResumeTool(db=_make_mock_db(), user_id=1)

        with patch("services.react_agent.tools.analyze_resume", new_callable=AsyncMock) as mock_analyze:
            mock_analyze.side_effect = [
                {"analysis": "experience result"},
                {"analysis": "score result"},
            ]

            await tool._execute(resume_id=1)

            # 应该调了 2 次，分别是 experience 和 score
            assert mock_analyze.call_count == 2
            called_types = [call.kwargs.get("analysis_type") or call.args[3] for call in mock_analyze.call_args_list]
            assert "experience" in called_types
            assert "score" in called_types

    @pytest.mark.asyncio
    async def test_handles_analysis_failure(self):
        """单个分析失败时仍返回部分结果。"""
        tool = DiagnoseResumeTool(db=_make_mock_db(), user_id=1)

        with patch("services.react_agent.tools.analyze_resume", new_callable=AsyncMock) as mock_analyze:
            mock_analyze.side_effect = [
                {"analysis": "经历分析正常"},
                HTTPException(status_code=500, detail="LLM 调用失败"),
            ]

            result = await tool._execute(resume_id=1)

        assert "经历分析正常" in result

    @pytest.mark.asyncio
    async def test_handles_all_analysis_failure(self):
        """所有分析都失败时返回错误提示。"""
        tool = DiagnoseResumeTool(db=_make_mock_db(), user_id=1)

        with patch("services.react_agent.tools.analyze_resume", new_callable=AsyncMock) as mock_analyze:
            mock_analyze.side_effect = HTTPException(status_code=404, detail="简历不存在")

            result = await tool._execute(resume_id=999)

        assert "不存在" in result or "失败" in result or "无法" in result


# ═══════════════════════════════════════════════════════════════
# CompareResumesTool
# ═══════════════════════════════════════════════════════════════


class TestCompareResumesTool:
    """多简历对比。"""

    @pytest.mark.asyncio
    async def test_returns_comparison(self):
        """返回对比结果。"""
        tool = CompareResumesTool(db=_make_mock_db(), user_id=1)

        with patch("services.react_agent.tools.compare_resumes", new_callable=AsyncMock) as mock_compare:
            mock_compare.return_value = {
                "resumes": [
                    {"id": 1, "filename": "resume_a.pdf"},
                    {"id": 2, "filename": "resume_b.pdf"},
                ],
                "dimensions": {
                    "skills": {"1": "Python, FastAPI", "2": "Java, Spring"},
                    "score": {"1": {"overall": 80}, "2": {"overall": 75}},
                },
            }

            result = await tool._execute(resume_ids=[1, 2])

        assert "resume_a" in result or "resume_b" in result
        assert "Python" in result or "Java" in result

    @pytest.mark.asyncio
    async def test_passes_resume_ids(self):
        """resume_ids 传递到 compare_resumes。"""
        tool = CompareResumesTool(db=_make_mock_db(), user_id=1)

        with patch("services.react_agent.tools.compare_resumes", new_callable=AsyncMock) as mock_compare:
            mock_compare.return_value = {"resumes": [], "dimensions": {}}

            await tool._execute(resume_ids=[10, 20])

            call_args = mock_compare.call_args
            all_args = list(call_args.args) + list(call_args.kwargs.values())
            assert [10, 20] in all_args

    @pytest.mark.asyncio
    async def test_handles_not_found(self):
        """简历不存在时返回提示。"""
        tool = CompareResumesTool(db=_make_mock_db(), user_id=1)

        with patch("services.react_agent.tools.compare_resumes", new_callable=AsyncMock) as mock_compare:
            mock_compare.side_effect = HTTPException(status_code=404, detail="简历不存在: [999]")

            result = await tool._execute(resume_ids=[1, 999])

        assert "不存在" in result or "找不到" in result or "无法" in result
