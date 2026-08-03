"""T12: 纯 LLM 工具 — rewrite_star / translate / interview_coach。

测试范围：
- 各工具调用 llm_generate 并返回结果
- 正确读取简历内容（qa 工具）
- 错误处理（简历不存在 / LLM 失败）
- target_position 传递到 prompt
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.react_agent.tools import (
    RewriteStarTool,
    TranslateTool,
    InterviewCoachTool,
)


# ── 辅助函数 ──────────────────────────────────────────────────


def _make_mock_db_with_resume(resume_id=1, parsed_text="3年Python后端，FastAPI项目经验"):
    """构造返回指定 resume 的 mock db。"""
    mock_resume = MagicMock()
    mock_resume.id = resume_id
    mock_resume.parsed_text = parsed_text
    mock_resume.status = "ready"

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_resume

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)
    return mock_db


def _make_mock_db_no_resume():
    """构造返回 None 的 mock db（简历不存在）。"""
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)
    return mock_db


# ═══════════════════════════════════════════════════════════════
# RewriteStarTool
# ═══════════════════════════════════════════════════════════════


class TestRewriteStarTool:
    """STAR 法则改写简历经历。"""

    @pytest.mark.asyncio
    async def test_returns_llm_response(self):
        """返回 LLM 改写结果。"""
        mock_db = _make_mock_db_with_resume()
        tool = RewriteStarTool(db=mock_db, user_id=1)

        with patch("services.react_agent.tools.llm_generate", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = "改写后的STAR经历"
            result = await tool._execute(resume_id=1, target_position="Python后端")

        assert result == "改写后的STAR经历"

    @pytest.mark.asyncio
    async def test_passes_resume_content_to_llm(self):
        """简历内容传递到 LLM prompt。"""
        mock_db = _make_mock_db_with_resume(parsed_text="我的原始简历内容")
        tool = RewriteStarTool(db=mock_db, user_id=1)

        with patch("services.react_agent.tools.llm_generate", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = "result"
            await tool._execute(resume_id=1, target_position="后端")

            call_kwargs = mock_llm.call_args
            # 简历内容应在 system 或 user prompt 中
            combined = (call_kwargs.kwargs.get("system", "") + call_kwargs.kwargs.get("user", ""))
            assert "原始简历内容" in combined

    @pytest.mark.asyncio
    async def test_passes_target_position(self):
        """目标岗位传递到 prompt。"""
        mock_db = _make_mock_db_with_resume()
        tool = RewriteStarTool(db=mock_db, user_id=1)

        with patch("services.react_agent.tools.llm_generate", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = "result"
            await tool._execute(resume_id=1, target_position="AI Agent工程师")

            call_kwargs = mock_llm.call_args
            combined = (call_kwargs.kwargs.get("system", "") + call_kwargs.kwargs.get("user", ""))
            assert "AI Agent工程师" in combined

    @pytest.mark.asyncio
    async def test_handles_missing_resume(self):
        """简历不存在时返回提示。"""
        mock_db = _make_mock_db_no_resume()
        tool = RewriteStarTool(db=mock_db, user_id=1)

        result = await tool._execute(resume_id=999, target_position="后端")
        assert "不存在" in result or "未找到" in result or "无法" in result

    @pytest.mark.asyncio
    async def test_works_without_target_position(self):
        """target_position 为 None 时仍可工作。"""
        mock_db = _make_mock_db_with_resume()
        tool = RewriteStarTool(db=mock_db, user_id=1)

        with patch("services.react_agent.tools.llm_generate", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = "通用改写结果"
            result = await tool._execute(resume_id=1, target_position=None)

        assert result == "通用改写结果"


# ═══════════════════════════════════════════════════════════════
# TranslateTool
# ═══════════════════════════════════════════════════════════════


class TestTranslateTool:
    """简历翻译。"""

    @pytest.mark.asyncio
    async def test_returns_llm_response(self):
        mock_db = _make_mock_db_with_resume()
        tool = TranslateTool(db=mock_db, user_id=1)

        with patch("services.react_agent.tools.llm_generate", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = "Translated resume"
            result = await tool._execute(resume_id=1, target_lang="en")

        assert result == "Translated resume"

    @pytest.mark.asyncio
    async def test_passes_target_lang_to_prompt(self):
        mock_db = _make_mock_db_with_resume()
        tool = TranslateTool(db=mock_db, user_id=1)

        with patch("services.react_agent.tools.llm_generate", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = "result"
            await tool._execute(resume_id=1, target_lang="ja")

            call_kwargs = mock_llm.call_args
            combined = (call_kwargs.kwargs.get("system", "") + call_kwargs.kwargs.get("user", ""))
            assert "ja" in combined or "日" in combined

    @pytest.mark.asyncio
    async def test_handles_missing_resume(self):
        mock_db = _make_mock_db_no_resume()
        tool = TranslateTool(db=mock_db, user_id=1)

        result = await tool._execute(resume_id=999, target_lang="en")
        assert "不存在" in result or "未找到" in result or "无法" in result


# ═══════════════════════════════════════════════════════════════
# InterviewCoachTool
# ═══════════════════════════════════════════════════════════════


class TestInterviewCoachTool:
    """模拟面试 Q&A。"""

    @pytest.mark.asyncio
    async def test_returns_llm_response(self):
        mock_db = _make_mock_db_with_resume()
        tool = InterviewCoachTool(db=mock_db, user_id=1)

        with patch("services.react_agent.tools.llm_generate", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = "面试问题和回答"
            result = await tool._execute(resume_id=1, target_position="Python后端")

        assert result == "面试问题和回答"

    @pytest.mark.asyncio
    async def test_passes_target_position(self):
        mock_db = _make_mock_db_with_resume()
        tool = InterviewCoachTool(db=mock_db, user_id=1)

        with patch("services.react_agent.tools.llm_generate", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = "result"
            await tool._execute(resume_id=1, target_position="数据工程师")

            call_kwargs = mock_llm.call_args
            combined = (call_kwargs.kwargs.get("system", "") + call_kwargs.kwargs.get("user", ""))
            assert "数据工程师" in combined

    @pytest.mark.asyncio
    async def test_handles_missing_resume(self):
        mock_db = _make_mock_db_no_resume()
        tool = InterviewCoachTool(db=mock_db, user_id=1)

        result = await tool._execute(resume_id=999, target_position="后端")
        assert "不存在" in result or "未找到" in result or "无法" in result

    @pytest.mark.asyncio
    async def test_max_rounds_in_prompt(self):
        """prompt 中包含最多 8 轮的限制。"""
        mock_db = _make_mock_db_with_resume()
        tool = InterviewCoachTool(db=mock_db, user_id=1)

        with patch("services.react_agent.tools.llm_generate", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = "result"
            await tool._execute(resume_id=1, target_position="后端")

            call_kwargs = mock_llm.call_args
            combined = (call_kwargs.kwargs.get("system", "") + call_kwargs.kwargs.get("user", ""))
            assert "8" in combined
