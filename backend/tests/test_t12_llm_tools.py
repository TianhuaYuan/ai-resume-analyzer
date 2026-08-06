"""T12: 纯 LLM 工具 — rewrite_star / translate / interview_coach。

测试范围：
- 各工具调用 llm_generate 并返回结果
- 正确读取简历内容（qa 工具）
- 错误处理（简历不存在 / LLM 失败）
- target_position 传递到 prompt
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.react_agent.tools import (
    RewriteStarTool,
    TranslateTool,
    InterviewCoachTool,
)


# ── 辅助函数 ──────────────────────────────────────────────────


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


# 确定性题单（单题，无追问 —— 便于断言推进/结束）
_PLAN_SINGLE = [
    {
        "id": "q1",
        "text": "请介绍一下你最有代表性的项目。",
        "section": "项目深挖",
        "difficulty": 3,
        "rubric": [{"criterion": "深度", "weight": 1.0, "description": "能讲清难点与结果"}],
        "followups": [],
        "target_competency": "项目深挖",
    }
]


def _make_sim(plan, cursor=0, followup_index=-1, answers=None, status="active"):
    """构造真实的 InterviewSimulation（非 Mock，状态机纯函数可直接操作）。"""
    from models.interview_simulation import InterviewSimulation

    return InterviewSimulation(
        user_id=1,
        resume_id=1,
        target_position="Python后端",
        plan=plan,
        cursor=cursor,
        followup_index=followup_index,
        answers=answers or [],
        status=status,
    )


class _FakeResult:
    """一次 execute 的结果：scalars().all() 与 scalar_one_or_none() 双通道。"""

    def __init__(self, rows, resume):
        self._rows = rows
        self._resume = resume

    def scalars(self):
        class _S:
            def all(_self):
                return self._rows

        return _S()

    def scalar_one_or_none(self):
        return self._resume


class _FakeDB:
    """支持 execute / add / commit / refresh 的最小异步 DB 桩。"""

    def __init__(self, rows=None, resume=None):
        self._rows = rows if rows is not None else []
        self._resume = resume

    async def execute(self, stmt):
        return _FakeResult(self._rows, self._resume)

    def add(self, obj):
        pass

    async def commit(self):
        pass

    async def refresh(self, obj):
        return obj


class TestInterviewCoachTool:
    """多轮模拟面试（阶段 5 H1-H3）：开始出第 1 题 → 答后推进 → 结束评分。"""

    @pytest.mark.asyncio
    async def test_start_returns_first_question(self):
        """无进行中面试 → 创建并返回第 1 题（含目标岗位与题号）。"""
        resume = MagicMock(parsed_text="3年Python后端，FastAPI项目经验", status="ready")
        mock_db = _FakeDB(rows=[], resume=resume)

        with patch("services.interview_coach.generate_plan",
                   new_callable=AsyncMock, return_value=_PLAN_SINGLE):
            tool = InterviewCoachTool(db=mock_db, user_id=1)
            result = await tool._execute(resume_id=1, target_position="Python后端")

        assert "Python后端" in result
        assert "第 1/1 题" in result
        assert "项目深挖" in result

    @pytest.mark.asyncio
    async def test_answer_records_and_completes(self):
        """单题面试：答完推进到末尾 → 自动结束并出评分卡。"""
        sim = _make_sim(_PLAN_SINGLE)
        mock_db = _FakeDB(rows=[sim])  # 有进行中的面试

        score_json = json.dumps(
            [{"question_id": "q1", "score": 80, "feedback": "好", "model_answer": "参考"}],
            ensure_ascii=False,
        )
        with patch("services.rag.pipeline.llm_generate",
                   new_callable=AsyncMock, return_value=score_json):
            tool = InterviewCoachTool(db=mock_db, user_id=1)
            result = await tool._execute(
                resume_id=1, target_position="Python后端", answer="我用Python做过交易系统"
            )

        assert sim.answers[0]["answer"] == "我用Python做过交易系统"
        assert sim.cursor == 1
        assert sim.status == "completed"
        assert "面试结束" in result

    @pytest.mark.asyncio
    async def test_no_answer_reasks_current(self):
        """无回答（answer 为空）→ 不推进，重问当前题。"""
        sim = _make_sim(_PLAN_SINGLE)
        mock_db = _FakeDB(rows=[sim])

        tool = InterviewCoachTool(db=mock_db, user_id=1)
        result = await tool._execute(resume_id=1, target_position="Python后端")

        assert sim.cursor == 0
        assert "第 1/1 题" in result
        assert sim.answers == []

    @pytest.mark.asyncio
    async def test_handles_missing_resume(self):
        """简历不存在 → 明确提示。"""
        mock_db = _FakeDB(rows=[], resume=None)
        tool = InterviewCoachTool(db=mock_db, user_id=1)

        result = await tool._execute(resume_id=999, target_position="后端")
        assert "不存在" in result
