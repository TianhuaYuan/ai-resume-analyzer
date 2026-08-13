"""T16: ReAct 核心循环测试。

测试范围（坏 tool_call 回灌是首个用例）：
1. 坏 tool_call 回灌：LLM 调不存在/参数非法的工具 → 错误回灌 → 收敛
2. 直接回答：LLM 不调工具，直接给出答案
3. 单工具调用：LLM 调一个工具 → 拿结果 → 回答
4. 多工具同轮：LLM 一轮调多个工具
5. 最大轮次强制收敛：LLM 持续调工具 → 达到上限 → 强制无工具回答
6. 配额检查：配额不足时中断
7. process_trace 记录：验证过程追踪正确
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.rag.pipeline import LLMToolResponse, ToolCall


# ── 辅助函数 ──────────────────────────────────────────────────


def _make_response(
    content="",
    tool_calls=None,
    reasoning="",
    usage=None,
):
    """构造 LLMToolResponse。"""
    return LLMToolResponse(
        content=content,
        tool_calls=tool_calls or [],
        reasoning_content=reasoning or None,
        usage=usage or {"prompt_tokens": 100, "completion_tokens": 50},
    )


def _make_tool_call(name="search_resume", arguments=None, call_id="tc_1"):
    """构造 ToolCall。"""
    return ToolCall(
        id=call_id,
        name=name,
        arguments=json.dumps(arguments or {"resume_id": 1, "query": "test"}),
    )


def _make_stream_response(content="", tool_calls=None, reasoning="", usage=None):
    """构造模拟 llm_generate_with_tools_stream 的 async generator。

    中间轮改流式后，react_loop 通过 _stream_middle_round 消费该流。
    对应 pipeline.py 流式事件协议：reasoning / token / usage / done。
    """
    async def _gen():
        if reasoning:
            yield {"type": "reasoning", "content": reasoning}
        if content:
            yield {"type": "token", "content": content}
        if usage:
            yield {
                "type": "usage",
                "prompt_tokens": usage.get("prompt_tokens", 0),
                "completion_tokens": usage.get("completion_tokens", 0),
            }
        yield {"type": "done", "content": content, "tool_calls": tool_calls or []}
    return _gen()


def _make_mock_tool_class(result="工具执行结果"):
    """构造 mock tool 类。"""
    mock_tool = MagicMock()
    mock_tool.execute = AsyncMock(return_value=result)
    mock_tool.last_usage = {"prompt_tokens": 0, "completion_tokens": 0}
    mock_tool.sources = []
    mock_tool_class = MagicMock(return_value=mock_tool)
    return mock_tool_class


def _patch_loop_deps(extra_patches=None):
    """批量 patch loop 模块的依赖，返回 patch dict。"""
    patches = {
        "llm_generate_with_tools": patch(
            "services.react_agent.loop.llm_generate_with_tools", new_callable=AsyncMock
        ),
        "assemble_system_prompt": patch(
            "services.react_agent.loop.assemble_system_prompt", new_callable=AsyncMock
        ),
        "check_quota": patch(
            "services.react_agent.loop.check_quota", new_callable=AsyncMock
        ),
        "manage_l1_context": patch(
            "services.react_agent.loop.manage_l1_context"
        ),
        "get_tool_by_name": patch(
            "services.react_agent.loop.get_tool_by_name"
        ),
        "get_agent_schemas": patch(
            "services.react_agent.loop.get_agent_schemas"
        ),
    }
    return patches


# ═══════════════════════════════════════════════════════════════
# 1. 坏 tool_call 回灌（首个用例）
# ═══════════════════════════════════════════════════════════════


class TestBadToolCallFeedback:
    """坏 tool_call 防御：名称不存在 / 参数非法 → 回灌错误 → 收敛。"""

    @pytest.mark.asyncio
    async def test_bad_tool_name_feedback_converges(self):
        """LLM 调不存在的工具名 → 错误回灌 → 第二轮直接回答。"""
        from services.react_agent.loop import react_loop

        stream_mock = MagicMock(side_effect=[
            _make_stream_response(tool_calls=[_make_tool_call(name="nonexistent_tool")]),
            _make_stream_response(content="这是最终答案"),
        ])

        with patch("services.react_agent.loop.assemble_system_prompt", new_callable=AsyncMock) as mock_sys, \
             patch("services.react_agent.loop.check_quota", new_callable=AsyncMock) as mock_quota, \
             patch("services.react_agent.loop.llm_generate_with_tools", new_callable=AsyncMock) as mock_llm, \
             patch("services.react_agent.loop.llm_generate_with_tools_stream", stream_mock), \
             patch("services.react_agent.loop.get_tool_by_name") as mock_get_tool, \
             patch("services.react_agent.loop.get_agent_schemas") as mock_schemas, \
             patch("services.react_agent.loop.manage_l1_context") as mock_l1:

            mock_sys.return_value = "system prompt"
            mock_quota.return_value = (True, None)
            mock_l1.side_effect = lambda msgs, **kw: msgs
            mock_schemas.return_value = []
            mock_get_tool.return_value = None  # 工具不存在

            # 第 1 轮：调不存在的工具（坏调用回灌）；第 2 轮：直接回答
            # 正常回答路径全走中间轮流式，最终轮仅强制收敛时调用
            mock_llm.return_value = _make_response(content="不应到达")

            result = await react_loop(db=AsyncMock(), user_id=1, resume_id=1, question="测试")

        assert "最终答案" in result.answer
        assert mock_llm.call_count == 0  # 正常路径不走最终轮非流式
        assert stream_mock.call_count == 2

    @pytest.mark.asyncio
    async def test_bad_tool_args_feedback_converges(self):
        """LLM 调工具参数非法 → 错误回灌 → 第二轮直接回答。"""
        from services.react_agent.loop import react_loop

        # 构造一个 execute 会 raise ValidationError 的 mock tool

        mock_tool_instance = MagicMock()
        mock_tool_instance.execute = AsyncMock(side_effect=Exception("参数校验失败"))
        mock_tool_class = MagicMock(return_value=mock_tool_instance)

        stream_mock = MagicMock(side_effect=[
            _make_stream_response(tool_calls=[_make_tool_call(
                name="search_resume",
                arguments={"bad_field": "invalid"},
            )]),
            _make_stream_response(content="收敛后的答案"),
        ])

        with patch("services.react_agent.loop.assemble_system_prompt", new_callable=AsyncMock) as mock_sys, \
             patch("services.react_agent.loop.check_quota", new_callable=AsyncMock) as mock_quota, \
             patch("services.react_agent.loop.llm_generate_with_tools", new_callable=AsyncMock) as mock_llm, \
             patch("services.react_agent.loop.llm_generate_with_tools_stream", stream_mock), \
             patch("services.react_agent.loop.get_tool_by_name", return_value=mock_tool_class), \
             patch("services.react_agent.loop.get_agent_schemas", return_value=[]), \
             patch("services.react_agent.loop.manage_l1_context") as mock_l1:

            mock_sys.return_value = "system prompt"
            mock_quota.return_value = (True, None)
            mock_l1.side_effect = lambda msgs, **kw: msgs

            mock_llm.return_value = _make_response(content="不应到达")

            result = await react_loop(db=AsyncMock(), user_id=1, resume_id=1, question="测试")

        assert "收敛后的答案" in result.answer


# ═══════════════════════════════════════════════════════════════
# 2. 直接回答
# ═══════════════════════════════════════════════════════════════


class TestDirectAnswer:
    """LLM 不调工具，直接给出答案。"""

    @pytest.mark.asyncio
    async def test_direct_answer_no_tools(self):
        from services.react_agent.loop import react_loop

        stream_mock = MagicMock(side_effect=[
            _make_stream_response(content="直接回答的答案"),
        ])

        with patch("services.react_agent.loop.assemble_system_prompt", new_callable=AsyncMock) as mock_sys, \
             patch("services.react_agent.loop.check_quota", new_callable=AsyncMock) as mock_quota, \
             patch("services.react_agent.loop.llm_generate_with_tools", new_callable=AsyncMock) as mock_llm, \
             patch("services.react_agent.loop.llm_generate_with_tools_stream", stream_mock), \
             patch("services.react_agent.loop.get_agent_schemas", return_value=[]), \
             patch("services.react_agent.loop.manage_l1_context") as mock_l1:

            mock_sys.return_value = "system prompt"
            mock_quota.return_value = (True, None)
            mock_l1.side_effect = lambda msgs, **kw: msgs
            mock_llm.return_value = _make_response(content="不应到达")

            result = await react_loop(db=AsyncMock(), user_id=1, resume_id=1, question="测试问题")

        assert result.answer == "直接回答的答案"
        assert mock_llm.call_count == 0  # 直接回答走中间轮流式
        assert stream_mock.call_count == 1


# ═══════════════════════════════════════════════════════════════
# 3. 单工具调用
# ═══════════════════════════════════════════════════════════════


class TestSingleToolCall:
    """LLM 调一个工具 → 拿结果 → 回答。"""

    @pytest.mark.asyncio
    async def test_single_tool_then_answer(self):
        from services.react_agent.loop import react_loop

        mock_tool_class = _make_mock_tool_class(result="检索到 3 条相关经历")

        stream_mock = MagicMock(side_effect=[
            _make_stream_response(tool_calls=[_make_tool_call(
                name="search_resume",
                arguments={"resume_id": 1, "query": "项目经历"},
            )]),
            _make_stream_response(content="根据检索结果，你有 3 段项目经历"),
        ])

        with patch("services.react_agent.loop.assemble_system_prompt", new_callable=AsyncMock) as mock_sys, \
             patch("services.react_agent.loop.check_quota", new_callable=AsyncMock) as mock_quota, \
             patch("services.react_agent.loop.llm_generate_with_tools", new_callable=AsyncMock) as mock_llm, \
             patch("services.react_agent.loop.llm_generate_with_tools_stream", stream_mock), \
             patch("services.react_agent.loop.get_tool_by_name", return_value=mock_tool_class), \
             patch("services.react_agent.loop.get_agent_schemas", return_value=[]), \
             patch("services.react_agent.loop.manage_l1_context") as mock_l1:

            mock_sys.return_value = "system prompt"
            mock_quota.return_value = (True, None)
            mock_l1.side_effect = lambda msgs, **kw: msgs

            mock_llm.return_value = _make_response(content="不应到达")

            result = await react_loop(db=AsyncMock(), user_id=1, resume_id=1, question="我的项目经历")

        assert "3 段项目经历" in result.answer
        assert mock_llm.call_count == 0  # 正常路径走中间轮流式
        assert stream_mock.call_count == 2


# ═══════════════════════════════════════════════════════════════
# 4. 多工具同轮
# ═══════════════════════════════════════════════════════════════


class TestMultipleToolsSameRound:
    """LLM 一轮调多个工具。"""

    @pytest.mark.asyncio
    async def test_two_tools_same_round(self):
        from services.react_agent.loop import react_loop

        mock_tool_class = _make_mock_tool_class(result="工具结果")

        stream_mock = MagicMock(side_effect=[
            _make_stream_response(tool_calls=[
                _make_tool_call(name="search_resume", arguments={"resume_id": 1, "query": "技能"}, call_id="tc_1"),
                _make_tool_call(name="diagnose_resume", arguments={"resume_id": 1}, call_id="tc_2"),
            ]),
            _make_stream_response(content="综合分析结果"),
        ])

        with patch("services.react_agent.loop.assemble_system_prompt", new_callable=AsyncMock) as mock_sys, \
             patch("services.react_agent.loop.check_quota", new_callable=AsyncMock) as mock_quota, \
             patch("services.react_agent.loop.llm_generate_with_tools", new_callable=AsyncMock) as mock_llm, \
             patch("services.react_agent.loop.llm_generate_with_tools_stream", stream_mock), \
             patch("services.react_agent.loop.get_tool_by_name", return_value=mock_tool_class), \
             patch("services.react_agent.loop.get_agent_schemas", return_value=[]), \
             patch("services.react_agent.loop.manage_l1_context") as mock_l1:

            mock_sys.return_value = "system prompt"
            mock_quota.return_value = (True, None)
            mock_l1.side_effect = lambda msgs, **kw: msgs

            mock_llm.return_value = _make_response(content="不应到达")

            result = await react_loop(db=AsyncMock(), user_id=1, resume_id=1, question="分析我的简历")

        assert "综合分析结果" in result.answer
        # 工具应该被调了 2 次
        assert mock_tool_class.return_value.execute.call_count == 2


# ═══════════════════════════════════════════════════════════════
# 5. 最大轮次强制收敛
# ═══════════════════════════════════════════════════════════════


class TestMaxRoundsConvergence:
    """LLM 持续调工具 → 达到上限 → 强制无工具回答。"""

    @pytest.mark.asyncio
    async def test_max_rounds_forced_answer(self):
        from services.react_agent.loop import react_loop

        mock_tool_class = _make_mock_tool_class(result="结果")

        # 每轮都调工具（中间轮流式），MAX_ROUNDS 轮后强制收敛走最终轮流式
        # 注意：async generator 不可复用，必须每轮生成独立实例（不能用 [g] * 6）
        stream_mock = MagicMock(side_effect=[
            _make_stream_response(tool_calls=[_make_tool_call()], content="中间轮思考")
            for _ in range(6)
        ] + [
            _make_stream_response(content="强制收敛的答案")
        ])

        with patch("services.react_agent.loop.assemble_system_prompt", new_callable=AsyncMock) as mock_sys, \
             patch("services.react_agent.loop.check_quota", new_callable=AsyncMock) as mock_quota, \
             patch("services.react_agent.loop.llm_generate_with_tools", new_callable=AsyncMock) as mock_llm, \
             patch("services.react_agent.loop.llm_generate_with_tools_stream", stream_mock), \
             patch("services.react_agent.loop.get_tool_by_name", return_value=mock_tool_class), \
             patch("services.react_agent.loop.get_agent_schemas", return_value=[]), \
             patch("services.react_agent.loop.manage_l1_context") as mock_l1:

            mock_sys.return_value = "system prompt"
            mock_quota.return_value = (True, None)
            mock_l1.side_effect = lambda msgs, **kw: msgs

            mock_llm.return_value = _make_response(content="不应到达")

            result = await react_loop(db=AsyncMock(), user_id=1, resume_id=1, question="测试")

        assert "强制收敛" in result.answer or "收敛" in result.answer or result.answer != ""
        assert mock_llm.call_count == 0  # 轮次耗尽后最终轮也走流式，非流式不再调用
        assert stream_mock.call_count == 7


# ═══════════════════════════════════════════════════════════════
# 6. 配额检查
# ═══════════════════════════════════════════════════════════════


class TestQuotaCheck:
    """配额不足时中断循环。"""

    @pytest.mark.asyncio
    async def test_quota_exceeded_returns_message(self):
        from services.react_agent.loop import react_loop

        with patch("services.react_agent.loop.assemble_system_prompt", new_callable=AsyncMock) as mock_sys, \
             patch("services.react_agent.loop.check_quota", new_callable=AsyncMock) as mock_quota, \
             patch("services.react_agent.loop.llm_generate_with_tools", new_callable=AsyncMock) as mock_llm, \
             patch("services.react_agent.loop.get_agent_schemas", return_value=[]):

            mock_sys.return_value = "system prompt"
            mock_quota.return_value = (False, "今日配额已用完")

            result = await react_loop(db=AsyncMock(), user_id=1, resume_id=1, question="测试")

        assert "配额" in result.answer or "额度" in result.answer or "不足" in result.answer
        assert mock_llm.call_count == 0  # 没调 LLM


# ═══════════════════════════════════════════════════════════════
# 7. process_trace 记录
# ═══════════════════════════════════════════════════════════════


class TestProcessTrace:
    """验证 process_trace 正确记录循环过程。"""

    @pytest.mark.asyncio
    async def test_trace_records_tool_call_and_result(self):
        from services.react_agent.loop import react_loop

        mock_tool_class = _make_mock_tool_class(result="检索结果")

        stream_mock = MagicMock(side_effect=[
            _make_stream_response(tool_calls=[_make_tool_call(name="search_resume")]),
            _make_stream_response(content="最终答案"),
        ])

        with patch("services.react_agent.loop.assemble_system_prompt", new_callable=AsyncMock) as mock_sys, \
             patch("services.react_agent.loop.check_quota", new_callable=AsyncMock) as mock_quota, \
             patch("services.react_agent.loop.llm_generate_with_tools", new_callable=AsyncMock) as mock_llm, \
             patch("services.react_agent.loop.llm_generate_with_tools_stream", stream_mock), \
             patch("services.react_agent.loop.get_tool_by_name", return_value=mock_tool_class), \
             patch("services.react_agent.loop.get_agent_schemas", return_value=[]), \
             patch("services.react_agent.loop.manage_l1_context") as mock_l1:

            mock_sys.return_value = "system prompt"
            mock_quota.return_value = (True, None)
            mock_l1.side_effect = lambda msgs, **kw: msgs

            mock_llm.return_value = _make_response(content="不应到达")

            result = await react_loop(db=AsyncMock(), user_id=1, resume_id=1, question="测试")

        # process_trace 应该包含 tool_call 和 tool_result 事件
        trace_types = [e["type"] for e in result.process_trace]
        assert "tool_call" in trace_types
        assert "tool_result" in trace_types
        assert "agent_done" in trace_types

    @pytest.mark.asyncio
    async def test_trace_records_tool_error(self):
        """坏工具调用记录为 tool_error。"""
        from services.react_agent.loop import react_loop

        stream_mock = MagicMock(side_effect=[
            _make_stream_response(tool_calls=[_make_tool_call(name="bad_tool")]),
            _make_stream_response(content="最终答案"),
        ])

        with patch("services.react_agent.loop.assemble_system_prompt", new_callable=AsyncMock) as mock_sys, \
             patch("services.react_agent.loop.check_quota", new_callable=AsyncMock) as mock_quota, \
             patch("services.react_agent.loop.llm_generate_with_tools", new_callable=AsyncMock) as mock_llm, \
             patch("services.react_agent.loop.llm_generate_with_tools_stream", stream_mock), \
             patch("services.react_agent.loop.get_tool_by_name", return_value=None), \
             patch("services.react_agent.loop.get_agent_schemas", return_value=[]), \
             patch("services.react_agent.loop.manage_l1_context") as mock_l1:

            mock_sys.return_value = "system prompt"
            mock_quota.return_value = (True, None)
            mock_l1.side_effect = lambda msgs, **kw: msgs

            mock_llm.return_value = _make_response(content="不应到达")

            result = await react_loop(db=AsyncMock(), user_id=1, resume_id=1, question="测试")

        trace_types = [e["type"] for e in result.process_trace]
        assert "tool_error" in trace_types
