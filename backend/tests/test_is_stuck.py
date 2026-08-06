"""M5: M3 next_step_prompt + is_stuck 防卡死测试。

复用 test_react_loop 的 react_loop mock 模式（流式中间轮 + patch 依赖）：
1. next_step_prompt：第 2 轮起注入引导（user 消息含 NEXT_STEP_PROMPT），首轮不注入
2. is_stuck：连续 3 轮相同 tool_call → 第 3 轮注入 STUCK_PROMPT 换策略提示
3. 参数变化不触发 stuck（签名不同）
4. _tool_round_signature 纯函数：同参同签名 / 异参异签名 / 顺序无关
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.rag.pipeline import LLMToolResponse, ToolCall
from services.react_agent.loop import (
    NEXT_STEP_PROMPT,
    STUCK_PROMPT,
    _tool_round_signature,
)


def _make_response(content="", tool_calls=None, usage=None, reasoning=""):
    return LLMToolResponse(
        content=content,
        tool_calls=tool_calls or [],
        reasoning_content=reasoning or None,
        usage=usage or {"prompt_tokens": 100, "completion_tokens": 50},
    )


def _make_tool_call(name="search_resume", arguments=None, call_id="tc_1"):
    return ToolCall(
        id=call_id,
        name=name,
        arguments=json.dumps(arguments or {"resume_id": 1, "query": "test"}),
    )


def _make_stream_response(content="", tool_calls=None, usage=None, reasoning=""):
    """构造模拟 llm_generate_with_tools_stream 的 async generator。"""
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


def _mock_tool_class():
    mc = MagicMock()
    mc.return_value.execute = AsyncMock(return_value="结果")
    mc.return_value.last_usage = {"prompt_tokens": 0, "completion_tokens": 0}
    mc.return_value.sources = []
    return mc


def _user_hints(messages) -> list[str]:
    """提取 messages 中 user 角色的文本。"""
    return [m["content"] for m in messages if m.get("role") == "user"]


class TestToolRoundSignature:
    """is_stuck 签名函数纯逻辑。"""

    def test_same_call_same_signature(self):
        a = _make_tool_call(name="search_resume", arguments={"resume_id": 1, "query": "Python"})
        b = _make_tool_call(name="search_resume", arguments={"resume_id": 1, "query": "Python"})
        assert _tool_round_signature([a]) == _tool_round_signature([b])

    def test_different_args_different_signature(self):
        a = _make_tool_call(name="search_resume", arguments={"resume_id": 1, "query": "Python"})
        b = _make_tool_call(name="search_resume", arguments={"resume_id": 1, "query": "Go"})
        assert _tool_round_signature([a]) != _tool_round_signature([b])

    def test_order_insensitive(self):
        a = _make_tool_call(name="search_resume", arguments={"resume_id": 1, "query": "Python"})
        b = _make_tool_call(name="diagnose_resume", arguments={"resume_id": 1})
        assert _tool_round_signature([a, b]) == _tool_round_signature([b, a])

    def test_empty_for_no_tools(self):
        assert _tool_round_signature([]) == ()


class TestNextStepPrompt:
    """next_step_prompt 注入（M3 OpenManus 借鉴①）。"""

    @pytest.mark.asyncio
    async def test_injected_from_round_two(self):
        """第 2 轮 LLM 调用前注入 NEXT_STEP_PROMPT 引导。"""
        from services.react_agent.loop import react_loop

        mock_tool_class = _mock_tool_class()
        stream_mock = MagicMock(side_effect=[
            _make_stream_response(tool_calls=[_make_tool_call()]),
            _make_stream_response(content="最终答案"),
        ])

        with patch("services.react_agent.loop.assemble_system_prompt", new_callable=AsyncMock) as mock_sys, \
             patch("services.react_agent.loop.check_quota", new_callable=AsyncMock) as mock_quota, \
             patch("services.react_agent.loop.llm_generate_with_tools", new_callable=AsyncMock) as mock_llm, \
             patch("services.react_agent.loop.llm_generate_with_tools_stream", stream_mock), \
             patch("services.react_agent.loop.get_tool_by_name", return_value=mock_tool_class), \
             patch("services.react_agent.loop.get_agent_schemas", return_value=[]), \
             patch("services.react_agent.loop.manage_l1_context") as mock_l1:

            mock_sys.return_value = "system"
            mock_quota.return_value = (True, None)
            mock_l1.side_effect = lambda msgs, **kw: msgs
            mock_llm.return_value = _make_response(content="不应到达")

            result = await react_loop(db=AsyncMock(), user_id=1, resume_id=1, question="测试")

        assert "最终答案" in result.answer
        second_msgs = stream_mock.call_args_list[1].kwargs["messages"]
        assert any("不要再调用工具" in h for h in _user_hints(second_msgs))

    @pytest.mark.asyncio
    async def test_not_injected_first_round(self):
        """首轮不注入引导（直接处理用户问题）。"""
        from services.react_agent.loop import react_loop

        stream_mock = MagicMock(side_effect=[_make_stream_response(content="答案")])

        with patch("services.react_agent.loop.assemble_system_prompt", new_callable=AsyncMock) as mock_sys, \
             patch("services.react_agent.loop.check_quota", new_callable=AsyncMock) as mock_quota, \
             patch("services.react_agent.loop.llm_generate_with_tools", new_callable=AsyncMock) as mock_llm, \
             patch("services.react_agent.loop.llm_generate_with_tools_stream", stream_mock), \
             patch("services.react_agent.loop.get_agent_schemas", return_value=[]), \
             patch("services.react_agent.loop.manage_l1_context") as mock_l1:

            mock_sys.return_value = "system"
            mock_quota.return_value = (True, None)
            mock_l1.side_effect = lambda msgs, **kw: msgs
            mock_llm.return_value = _make_response(content="不应到达")

            await react_loop(db=AsyncMock(), user_id=1, resume_id=1, question="测试")

        first_msgs = stream_mock.call_args_list[0].kwargs["messages"]
        assert not any("不要再调用工具" in h for h in _user_hints(first_msgs))


class TestIsStuck:
    """is_stuck 防卡死（M3 OpenManus 借鉴②）。"""

    @pytest.mark.asyncio
    async def test_repeated_tool_call_injects_stuck_prompt(self):
        """连续 3 轮相同 tool_call → 第 3 轮注入 STUCK_PROMPT 换策略提示。"""
        from services.react_agent.loop import react_loop

        mock_tool_class = _mock_tool_class()
        same_call = _make_tool_call(
            name="search_resume", arguments={"resume_id": 1, "query": "Python"}
        )
        stream_mock = MagicMock(side_effect=[
            _make_stream_response(tool_calls=[same_call]),  # 轮1：签名记录，不 stuck
            _make_stream_response(tool_calls=[same_call]),  # 轮2：签名重复 ≥2 → stuck
            _make_stream_response(content="最终答案"),       # 轮3：注入 STUCK_PROMPT
        ])

        with patch("services.react_agent.loop.assemble_system_prompt", new_callable=AsyncMock) as mock_sys, \
             patch("services.react_agent.loop.check_quota", new_callable=AsyncMock) as mock_quota, \
             patch("services.react_agent.loop.llm_generate_with_tools", new_callable=AsyncMock) as mock_llm, \
             patch("services.react_agent.loop.llm_generate_with_tools_stream", stream_mock), \
             patch("services.react_agent.loop.get_tool_by_name", return_value=mock_tool_class), \
             patch("services.react_agent.loop.get_agent_schemas", return_value=[]), \
             patch("services.react_agent.loop.manage_l1_context") as mock_l1:

            mock_sys.return_value = "system"
            mock_quota.return_value = (True, None)
            mock_l1.side_effect = lambda msgs, **kw: msgs
            mock_llm.return_value = _make_response(content="不应到达")

            result = await react_loop(db=AsyncMock(), user_id=1, resume_id=1, question="测试")

        assert "最终答案" in result.answer
        third_msgs = stream_mock.call_args_list[2].kwargs["messages"]
        assert any("陷入" in h or "换一种" in h for h in _user_hints(third_msgs))

    @pytest.mark.asyncio
    async def test_varied_calls_do_not_trigger_stuck(self):
        """参数变化的调用不触发 stuck（签名不同）。"""
        from services.react_agent.loop import react_loop

        mock_tool_class = _mock_tool_class()
        call1 = _make_tool_call(name="search_resume", arguments={"resume_id": 1, "query": "Python"})
        call2 = _make_tool_call(name="search_resume", arguments={"resume_id": 1, "query": "Go"})
        stream_mock = MagicMock(side_effect=[
            _make_stream_response(tool_calls=[call1]),
            _make_stream_response(tool_calls=[call2]),
            _make_stream_response(content="最终答案"),
        ])

        with patch("services.react_agent.loop.assemble_system_prompt", new_callable=AsyncMock) as mock_sys, \
             patch("services.react_agent.loop.check_quota", new_callable=AsyncMock) as mock_quota, \
             patch("services.react_agent.loop.llm_generate_with_tools", new_callable=AsyncMock) as mock_llm, \
             patch("services.react_agent.loop.llm_generate_with_tools_stream", stream_mock), \
             patch("services.react_agent.loop.get_tool_by_name", return_value=mock_tool_class), \
             patch("services.react_agent.loop.get_agent_schemas", return_value=[]), \
             patch("services.react_agent.loop.manage_l1_context") as mock_l1:

            mock_sys.return_value = "system"
            mock_quota.return_value = (True, None)
            mock_l1.side_effect = lambda msgs, **kw: msgs
            mock_llm.return_value = _make_response(content="不应到达")

            await react_loop(db=AsyncMock(), user_id=1, resume_id=1, question="测试")

        third_msgs = stream_mock.call_args_list[2].kwargs["messages"]
        assert not any("陷入" in h or "换一种" in h for h in _user_hints(third_msgs))

    @pytest.mark.asyncio
    async def test_stuck_prompt_resets_after_injection(self):
        """stuck 提示注入后重置标志：第 4 轮若恢复正常调用不再注入 STUCK。"""
        from services.react_agent.loop import react_loop

        mock_tool_class = _mock_tool_class()
        same_call = _make_tool_call(name="search_resume", arguments={"resume_id": 1, "query": "Python"})
        diff_call = _make_tool_call(name="search_resume", arguments={"resume_id": 1, "query": "Go"})
        stream_mock = MagicMock(side_effect=[
            _make_stream_response(tool_calls=[same_call]),  # 轮1
            _make_stream_response(tool_calls=[same_call]),  # 轮2 → stuck=True
            _make_stream_response(tool_calls=[same_call]),  # 轮3 → 注入 STUCK（重置 stuck）
            _make_stream_response(content="最终答案"),       # 轮4 → 仅 NEXT_STEP
        ])

        with patch("services.react_agent.loop.assemble_system_prompt", new_callable=AsyncMock) as mock_sys, \
             patch("services.react_agent.loop.check_quota", new_callable=AsyncMock) as mock_quota, \
             patch("services.react_agent.loop.llm_generate_with_tools", new_callable=AsyncMock) as mock_llm, \
             patch("services.react_agent.loop.llm_generate_with_tools_stream", stream_mock), \
             patch("services.react_agent.loop.get_tool_by_name", return_value=mock_tool_class), \
             patch("services.react_agent.loop.get_agent_schemas", return_value=[]), \
             patch("services.react_agent.loop.manage_l1_context") as mock_l1:

            mock_sys.return_value = "system"
            mock_quota.return_value = (True, None)
            mock_l1.side_effect = lambda msgs, **kw: msgs
            mock_llm.return_value = _make_response(content="不应到达")

            await react_loop(db=AsyncMock(), user_id=1, resume_id=1, question="测试")

        # 轮4 调用含 NEXT_STEP（通用引导），但本轮不应再注入 STUCK 变体（标志已重置）。
        # 历史轮次的 STUCK 提示仍留在上下文 messages 里，故断言只看本轮最后注入的 hint。
        fourth_msgs = stream_mock.call_args_list[3].kwargs["messages"]
        hints = _user_hints(fourth_msgs)
        assert any("不要再调用工具" in h for h in hints)
        assert not any("陷入" in h or "换一种" in h for h in hints[-1:])
