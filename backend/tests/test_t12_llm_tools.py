"""T12: 纯 LLM 工具 — rewrite_star / translate / interview_coach / generate_greeting / reply_draft。

测试范围：
- 各工具调用 llm_generate 并返回结果
- 正确读取简历内容（qa 工具）或 L3 画像（workbench 工具）
- 错误处理（简历不存在 / LLM 失败）
- target_position 传递到 prompt
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.react_agent.tools import (
    RewriteStarTool,
    TranslateTool,
    InterviewCoachTool,
    GenerateGreetingTool,
    ReplyDraftTool,
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


# ═══════════════════════════════════════════════════════════════
# GenerateGreetingTool
# ═══════════════════════════════════════════════════════════════


class TestGenerateGreetingTool:
    """生成打招呼语（workbench 工具，读 L3 画像）。"""

    @pytest.mark.asyncio
    async def test_returns_llm_response(self):
        tool = GenerateGreetingTool(db=AsyncMock(), user_id=1)

        with patch("services.react_agent.tools.get_l3_profile", new_callable=AsyncMock) as mock_l3, \
             patch("services.react_agent.tools.llm_generate", new_callable=AsyncMock) as mock_llm:
            mock_l3.return_value = {"summary": "3年Python后端", "skills": ["Python", "FastAPI"]}
            mock_llm.return_value = "你好，我是3年经验的Python后端..."

            result = await tool._execute(resume_id=1, target_position="Python后端")

        assert result == "你好，我是3年经验的Python后端..."

    @pytest.mark.asyncio
    async def test_passes_l3_profile_to_prompt(self):
        tool = GenerateGreetingTool(db=AsyncMock(), user_id=1)

        with patch("services.react_agent.tools.get_l3_profile", new_callable=AsyncMock) as mock_l3, \
             patch("services.react_agent.tools.llm_generate", new_callable=AsyncMock) as mock_llm:
            mock_l3.return_value = {"summary": "5年Java架构师", "skills": ["Java", "Spring"]}
            mock_llm.return_value = "result"

            await tool._execute(resume_id=1, target_position="架构师")

            call_kwargs = mock_llm.call_args
            combined = (call_kwargs.kwargs.get("system", "") + call_kwargs.kwargs.get("user", ""))
            assert "5年Java架构师" in combined or "Java" in combined

    @pytest.mark.asyncio
    async def test_works_without_l3_profile(self):
        """无 L3 画像时仍可工作（降级）。"""
        tool = GenerateGreetingTool(db=AsyncMock(), user_id=1)

        with patch("services.react_agent.tools.get_l3_profile", new_callable=AsyncMock) as mock_l3, \
             patch("services.react_agent.tools.llm_generate", new_callable=AsyncMock) as mock_llm:
            mock_l3.return_value = None
            mock_llm.return_value = "通用打招呼语"

            result = await tool._execute(resume_id=1, target_position="后端")

        assert result == "通用打招呼语"

    @pytest.mark.asyncio
    async def test_passes_target_position(self):
        tool = GenerateGreetingTool(db=AsyncMock(), user_id=1)

        with patch("services.react_agent.tools.get_l3_profile", new_callable=AsyncMock) as mock_l3, \
             patch("services.react_agent.tools.llm_generate", new_callable=AsyncMock) as mock_llm:
            mock_l3.return_value = None
            mock_llm.return_value = "result"

            await tool._execute(resume_id=1, target_position="前端工程师")

            call_kwargs = mock_llm.call_args
            combined = (call_kwargs.kwargs.get("system", "") + call_kwargs.kwargs.get("user", ""))
            assert "前端工程师" in combined


# ═══════════════════════════════════════════════════════════════
# ReplyDraftTool
# ═══════════════════════════════════════════════════════════════


class TestReplyDraftTool:
    """生成 HR 回复话术（workbench 工具，读 L3 画像）。"""

    @pytest.mark.asyncio
    async def test_returns_llm_response(self):
        tool = ReplyDraftTool(db=AsyncMock(), user_id=1)

        with patch("services.react_agent.tools.get_l3_profile", new_callable=AsyncMock) as mock_l3, \
             patch("services.react_agent.tools.llm_generate", new_callable=AsyncMock) as mock_llm:
            mock_l3.return_value = {"summary": "后端工程师", "skills": ["Python"]}
            mock_llm.return_value = "HR您好，感谢回复..."

            result = await tool._execute(
                resume_id=1, hr_message="你好，请问你什么时候可以面试？", target_position="后端"
            )

        assert result == "HR您好，感谢回复..."

    @pytest.mark.asyncio
    async def test_passes_hr_message_to_prompt(self):
        tool = ReplyDraftTool(db=AsyncMock(), user_id=1)

        with patch("services.react_agent.tools.get_l3_profile", new_callable=AsyncMock) as mock_l3, \
             patch("services.react_agent.tools.llm_generate", new_callable=AsyncMock) as mock_llm:
            mock_l3.return_value = None
            mock_llm.return_value = "result"

            await tool._execute(
                resume_id=1,
                hr_message="请问你的期望薪资是多少？",
                target_position="后端",
            )

            call_kwargs = mock_llm.call_args
            combined = (call_kwargs.kwargs.get("system", "") + call_kwargs.kwargs.get("user", ""))
            assert "期望薪资" in combined

    @pytest.mark.asyncio
    async def test_passes_target_position(self):
        tool = ReplyDraftTool(db=AsyncMock(), user_id=1)

        with patch("services.react_agent.tools.get_l3_profile", new_callable=AsyncMock) as mock_l3, \
             patch("services.react_agent.tools.llm_generate", new_callable=AsyncMock) as mock_llm:
            mock_l3.return_value = None
            mock_llm.return_value = "result"

            await tool._execute(
                resume_id=1,
                hr_message="你好",
                target_position="全栈工程师",
            )

            call_kwargs = mock_llm.call_args
            combined = (call_kwargs.kwargs.get("system", "") + call_kwargs.kwargs.get("user", ""))
            assert "全栈工程师" in combined

    @pytest.mark.asyncio
    async def test_works_without_l3_profile(self):
        tool = ReplyDraftTool(db=AsyncMock(), user_id=1)

        with patch("services.react_agent.tools.get_l3_profile", new_callable=AsyncMock) as mock_l3, \
             patch("services.react_agent.tools.llm_generate", new_callable=AsyncMock) as mock_llm:
            mock_l3.return_value = None
            mock_llm.return_value = "通用回复"

            result = await tool._execute(
                resume_id=1, hr_message="你好", target_position="后端"
            )

        assert result == "通用回复"
