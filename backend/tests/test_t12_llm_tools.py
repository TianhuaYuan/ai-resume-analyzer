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
    """STAR 法则改写简历经历。

    v2 实现：改写通过 function calling（submit_rewritten_resume）提交模块草稿，
    不再是直接 llm_generate 返回文本 —— 这里验证工具正确读模块上下文、
    装配 prompt 并调用 _submit_modules_via_llm 提交。
    """

    def _patch_rewrite_deps(self):
        """构造 rewrite_star 依赖：简历 + 模块上下文 + 提交确认。"""
        resume = MagicMock(status="draft", parsed_text="3年Python后端")
        resume.id = 1
        module = MagicMock()
        module.module_type = "work_experience"
        module.content = {"entries": [{"company": "字节", "position": "后端", "description": "做了一些事"}]}
        confirm = "✅ 简历已重写为草稿，共 1 个模块已保存。"
        return resume, [module], confirm

    @pytest.mark.asyncio
    async def test_returns_llm_response(self):
        """改写完成返回模块草稿保存确认。"""
        resume, modules, confirm = self._patch_rewrite_deps()

        with patch("services.react_agent.tools.get_resume_with_modules",
                   new_callable=AsyncMock, return_value=(resume, modules)), \
             patch("services.react_agent.tools._submit_modules_via_llm",
                   new_callable=AsyncMock, return_value=confirm) as mock_submit:
            result = await RewriteStarTool(db=MagicMock(), user_id=1)._execute(
                resume_id=1, target_position="Python后端")

        assert result == confirm
        mock_submit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_passes_resume_content_to_llm(self):
        """简历模块内容传递到 LLM prompt。"""
        resume, modules, confirm = self._patch_rewrite_deps()

        with patch("services.react_agent.tools.get_resume_with_modules",
                   new_callable=AsyncMock, return_value=(resume, modules)), \
             patch("services.react_agent.tools._submit_modules_via_llm",
                   new_callable=AsyncMock, return_value=confirm) as mock_submit:
            await RewriteStarTool(db=MagicMock(), user_id=1)._execute(
                resume_id=1, target_position="后端")

        # 模块内容（公司名）应出现在 user prompt（当前简历模块）中
        system, user_msg = mock_submit.await_args.args[2], mock_submit.await_args.args[3]
        assert "字节" in system + user_msg

    @pytest.mark.asyncio
    async def test_passes_target_position(self):
        """目标岗位传递到 prompt。"""
        resume, modules, confirm = self._patch_rewrite_deps()

        with patch("services.react_agent.tools.get_resume_with_modules",
                   new_callable=AsyncMock, return_value=(resume, modules)), \
             patch("services.react_agent.tools._submit_modules_via_llm",
                   new_callable=AsyncMock, return_value=confirm) as mock_submit:
            await RewriteStarTool(db=MagicMock(), user_id=1)._execute(
                resume_id=1, target_position="AI Agent工程师")

        system, user_msg = mock_submit.await_args.args[2], mock_submit.await_args.args[3]
        assert "AI Agent工程师" in system + user_msg

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
        resume, modules, confirm = self._patch_rewrite_deps()

        with patch("services.react_agent.tools.get_resume_with_modules",
                   new_callable=AsyncMock, return_value=(resume, modules)), \
             patch("services.react_agent.tools._submit_modules_via_llm",
                   new_callable=AsyncMock, return_value=confirm) as mock_submit:
            result = await RewriteStarTool(db=MagicMock(), user_id=1)._execute(
                resume_id=1, target_position=None)

        assert result == confirm
        mock_submit.assert_awaited_once()


# ═══════════════════════════════════════════════════════════════
# TranslateTool
# ═══════════════════════════════════════════════════════════════


class TestTranslateTool:
    """简历翻译。

    v2 实现：翻译通过 function calling（submit_rewritten_resume）提交模块草稿，
    不再是直接 llm_generate 返回文本。
    """

    def _patch_translate_deps(self):
        """构造 translate 依赖：简历 + 模块上下文 + 提交确认。"""
        resume = MagicMock(status="draft", parsed_text="3年Python后端")
        resume.id = 1
        module = MagicMock()
        module.module_type = "basic_info"
        module.content = {"name": "张三"}
        confirm = "✅ 简历已重写为草稿，共 1 个模块已保存。"
        return resume, [module], confirm

    @pytest.mark.asyncio
    async def test_returns_llm_response(self):
        """翻译完成返回模块草稿保存确认。"""
        resume, modules, confirm = self._patch_translate_deps()

        with patch("services.react_agent.tools.get_resume_with_modules",
                   new_callable=AsyncMock, return_value=(resume, modules)), \
             patch("services.react_agent.tools._submit_modules_via_llm",
                   new_callable=AsyncMock, return_value=confirm) as mock_submit:
            result = await TranslateTool(db=MagicMock(), user_id=1)._execute(
                resume_id=1, target_lang="en")

        assert result == confirm
        mock_submit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_passes_target_lang_to_prompt(self):
        """目标语言（映射后的语言名）传递到 prompt。"""
        resume, modules, confirm = self._patch_translate_deps()

        with patch("services.react_agent.tools.get_resume_with_modules",
                   new_callable=AsyncMock, return_value=(resume, modules)), \
             patch("services.react_agent.tools._submit_modules_via_llm",
                   new_callable=AsyncMock, return_value=confirm) as mock_submit:
            await TranslateTool(db=MagicMock(), user_id=1)._execute(
                resume_id=1, target_lang="ja")

        system, user_msg = mock_submit.await_args.args[2], mock_submit.await_args.args[3]
        combined = system + user_msg
        # ja → 日本語（_LANG_MAP 映射）
        assert "日本語" in combined or "ja" in combined

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
