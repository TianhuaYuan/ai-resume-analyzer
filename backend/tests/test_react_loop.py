"""ReAct 循环集成测试。

补充 T16 单元测试未覆盖的场景：
1. token 入账：多轮 LLM 调用的 usage 累加正确
2. event_callback：事件实时推送到回调
3. 坏 JSON 参数：tool_arguments 非法 JSON → 错误回灌
4. 连续坏调用强制收敛：MAX_TOOL_RETRIES=3（per-tool 预算）→ 跳出循环
5. history 参数：历史消息正确注入
6. Semaphore 并发：不阻塞单次执行
"""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.rag.pipeline import LLMToolResponse, ToolCall
from services.react_agent.loop import (
    _cleanup_resume_write_lock,
    _extract_direct_answer,
    _resume_write_lock,
    _resume_write_locks,
    _stabilize_tool_call_ids,
)


# ── 辅助函数 ──────────────────────────────────────────────────


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
    """构造模拟 llm_generate_with_tools_stream 的 async generator。

    中间轮改流式后，react_loop 通过 _stream_middle_round 消费该流。
    对应 pipeline.py 流式事件协议：reasoning / token / usage / done。
    注意：async generator 不可复用，多轮需各自生成独立实例。
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


def test_tool_call_ids_are_unique_when_provider_omits_or_reuses_ids():
    calls = [
        ToolCall(id="", name="generate_module", arguments="{}"),
        ToolCall(id="provider-id", name="search_resume", arguments="{}"),
        ToolCall(id="provider-id", name="rewrite_star", arguments="{}"),
    ]
    _stabilize_tool_call_ids(calls, 2)
    ids = [call.id for call in calls]
    assert all(ids)
    assert len(set(ids)) == len(ids)


def test_resume_write_lock_cleanup_is_identity_safe():
    resume_id = 987654321
    lock = _resume_write_lock(resume_id)
    _cleanup_resume_write_lock(resume_id, lock)
    assert resume_id not in _resume_write_locks


def test_extract_direct_answer_keeps_structured_artifacts_out_of_chat_answer():
    raw = (
        "[[DIRECT_ANSWER]]\n## JD 匹配结果\n谨慎结论"
        '\n\n<match_result>{"scores":{"overall":80}}</match_result>'
    )
    answer, visible = _extract_direct_answer(raw)
    assert answer == "## JD 匹配结果\n谨慎结论"
    assert visible.startswith("## JD 匹配结果")
    assert "<match_result>" in visible


def _patch_loop():
    """批量 patch loop 依赖，返回 (patches_dict, mock_dict)。"""
    mock_llm = AsyncMock()
    mock_sys = AsyncMock(return_value="system prompt")
    mock_quota = AsyncMock(return_value=(True, None))
    mock_l1 = MagicMock(side_effect=lambda msgs, **kw: msgs)
    mock_schemas = MagicMock(return_value=[])

    return {
        "llm": patch("services.react_agent.loop.llm_generate_with_tools", new=mock_llm),
        "sys": patch("services.react_agent.loop.assemble_system_prompt", new=mock_sys),
        "quota": patch("services.react_agent.loop.check_quota", new=mock_quota),
        "l1": patch("services.react_agent.loop.manage_l1_context", new=mock_l1),
        "schemas": patch("services.react_agent.loop.get_agent_schemas", new=mock_schemas),
    }


# ═══════════════════════════════════════════════════════════════
# 1. token 入账
# ═══════════════════════════════════════════════════════════════


class TestTokenAccumulation:
    """多轮 LLM 调用的 usage 累加。"""

    @pytest.mark.asyncio
    async def test_usage_accumulated_across_rounds(self):
        """两轮 LLM 调用的 token 分别累加到 result.usage。"""
        from services.react_agent.loop import react_loop

        mock_tool_class = MagicMock()
        mock_tool_class.return_value.execute = AsyncMock(return_value="结果")
        mock_tool_class.return_value.last_usage = {"prompt_tokens": 0, "completion_tokens": 0}
        mock_tool_class.return_value.sources = []

        # 两轮都走中间轮流式：第一轮调工具（200/80），第二轮直接答（150/60）
        stream_mock = MagicMock(side_effect=[
            _make_stream_response(
                tool_calls=[_make_tool_call()],
                usage={"prompt_tokens": 200, "completion_tokens": 80},
            ),
            _make_stream_response(
                content="最终答案",
                usage={"prompt_tokens": 150, "completion_tokens": 60},
            ),
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

        assert result.usage["prompt_tokens"] == 350
        assert result.usage["completion_tokens"] == 140

    @pytest.mark.asyncio
    async def test_usage_zero_when_quota_exceeded(self):
        """配额不足时 usage 为 0（没调 LLM）。"""
        from services.react_agent.loop import react_loop

        with patch("services.react_agent.loop.assemble_system_prompt", new_callable=AsyncMock), \
             patch("services.react_agent.loop.check_quota", new_callable=AsyncMock) as mock_quota, \
             patch("services.react_agent.loop.llm_generate_with_tools", new_callable=AsyncMock) as mock_llm, \
             patch("services.react_agent.loop.get_agent_schemas", return_value=[]):

            mock_quota.return_value = (False, "额度用完")

            result = await react_loop(db=AsyncMock(), user_id=1, resume_id=1, question="测试")

        assert result.usage["prompt_tokens"] == 0
        assert result.usage["completion_tokens"] == 0
        mock_llm.assert_not_called()

    @pytest.mark.asyncio
    async def test_usage_includes_forced_convergence_round(self):
        """强制收敛轮的 usage 也累加。"""
        from services.react_agent.loop import react_loop, MAX_TOOL_RETRIES

        # 构造连续 MAX_TOOL_RETRIES 次坏调用 + 强制收敛
        # 连续坏调用走中间轮流式（各 50/10），强制收敛走最终轮流式（300/100）
        stream_mock = MagicMock(side_effect=[
            _make_stream_response(
                tool_calls=[_make_tool_call(name="nonexistent")],
                usage={"prompt_tokens": 50, "completion_tokens": 10},
            )
            for _ in range(MAX_TOOL_RETRIES)
        ] + [
            _make_stream_response(
                content="强制收敛答案",
                usage={"prompt_tokens": 300, "completion_tokens": 100},
            )
        ])

        with patch("services.react_agent.loop.assemble_system_prompt", new_callable=AsyncMock) as mock_sys, \
             patch("services.react_agent.loop.check_quota", new_callable=AsyncMock) as mock_quota, \
             patch("services.react_agent.loop.llm_generate_with_tools", new_callable=AsyncMock) as mock_llm, \
             patch("services.react_agent.loop.llm_generate_with_tools_stream", stream_mock), \
             patch("services.react_agent.loop.get_tool_by_name", return_value=None), \
             patch("services.react_agent.loop.get_agent_schemas", return_value=[]), \
             patch("services.react_agent.loop.manage_l1_context") as mock_l1:

            mock_sys.return_value = "system"
            mock_quota.return_value = (True, None)
            mock_l1.side_effect = lambda msgs, **kw: msgs

            mock_llm.return_value = _make_response(content="不应到达")

            result = await react_loop(db=AsyncMock(), user_id=1, resume_id=1, question="测试")

        # MAX_TOOL_RETRIES 轮坏调用 * (50+10) + 1 轮强制收敛 * (300+100)
        expected_prompt = MAX_TOOL_RETRIES * 50 + 300
        expected_completion = MAX_TOOL_RETRIES * 10 + 100
        assert result.usage["prompt_tokens"] == expected_prompt
        assert result.usage["completion_tokens"] == expected_completion


# ═══════════════════════════════════════════════════════════════
# 2. event_callback
# ═══════════════════════════════════════════════════════════════


class TestEventCallback:
    """事件回调实时推送。"""

    @pytest.mark.asyncio
    async def test_callback_receives_all_events(self):
        """event_callback 收到 tool_call + tool_result + agent_done 事件。"""
        from services.react_agent.loop import react_loop

        mock_tool_class = MagicMock()
        mock_tool_class.return_value.execute = AsyncMock(return_value="检索结果")

        events_received: list[dict] = []

        async def callback(event: dict):
            events_received.append(event)

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

            mock_sys.return_value = "system"
            mock_quota.return_value = (True, None)
            mock_l1.side_effect = lambda msgs, **kw: msgs

            mock_llm.return_value = _make_response(content="不应到达")

            result = await react_loop(
                db=AsyncMock(), user_id=1, resume_id=1, question="测试",
                event_callback=callback,
            )

        types = [e["type"] for e in events_received]
        assert "tool_call" in types
        assert "tool_result" in types
        assert "agent_done" in types
        # process_trace 也应该和 callback 一致（排除不入 trace 的透传事件 tool_stream / answer_token）
        traceable = [e for e in events_received if e["type"] not in ("tool_stream", "answer_token")]
        assert len(result.process_trace) == len(traceable)

    @pytest.mark.asyncio
    async def test_callback_receives_quota_exceeded(self):
        """配额不足时 callback 收到 quota_exceeded 事件。"""
        from services.react_agent.loop import react_loop

        events_received: list[dict] = []

        async def callback(event: dict):
            events_received.append(event)

        with patch("services.react_agent.loop.assemble_system_prompt", new_callable=AsyncMock), \
             patch("services.react_agent.loop.check_quota", new_callable=AsyncMock) as mock_quota, \
             patch("services.react_agent.loop.llm_generate_with_tools", new_callable=AsyncMock) as mock_llm, \
             patch("services.react_agent.loop.get_agent_schemas", return_value=[]):

            mock_quota.return_value = (False, "额度用完")

            await react_loop(
                db=AsyncMock(), user_id=1, resume_id=1, question="测试",
                event_callback=callback,
            )

        types = [e["type"] for e in events_received]
        assert "quota_exceeded" in types
        mock_llm.assert_not_called()

    @pytest.mark.asyncio
    async def test_callback_receives_tool_error(self):
        """坏工具调用时 callback 收到 tool_error 事件。"""
        from services.react_agent.loop import react_loop

        events_received: list[dict] = []

        async def callback(event: dict):
            events_received.append(event)

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

            mock_sys.return_value = "system"
            mock_quota.return_value = (True, None)
            mock_l1.side_effect = lambda msgs, **kw: msgs

            mock_llm.return_value = _make_response(content="不应到达")

            await react_loop(
                db=AsyncMock(), user_id=1, resume_id=1, question="测试",
                event_callback=callback,
            )

        error_events = [e for e in events_received if e["type"] == "tool_error"]
        assert len(error_events) == 1
        assert "bad_tool" in error_events[0]["name"]


# ═══════════════════════════════════════════════════════════════
# 3. 坏 JSON 参数
# ═══════════════════════════════════════════════════════════════


class TestBadJsonArgs:
    """tool_arguments 为非法 JSON 时的回灌。"""

    @pytest.mark.asyncio
    async def test_malformed_json_args_returned_as_error(self):
        """arguments 不是合法 JSON → 错误回灌 → 第二轮回答。"""
        from services.react_agent.loop import react_loop

        mock_tool_class = MagicMock()
        mock_tool_class.return_value.execute = AsyncMock(return_value="不应到达")

        # 构造 arguments 为非法 JSON 的 ToolCall
        bad_call = ToolCall(id="tc_bad", name="search_resume", arguments="{invalid json}")
        stream_mock = MagicMock(side_effect=[
            _make_stream_response(tool_calls=[bad_call]),
            _make_stream_response(content="恢复后的答案"),
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

        assert "恢复后的答案" in result.answer
        # 工具的 execute 不应被调用（JSON 解析就失败了）
        mock_tool_class.return_value.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_empty_json_args_handled(self):
        """arguments 为空字符串 → 当作 {} 处理。"""
        from services.react_agent.loop import react_loop

        mock_tool_class = MagicMock()
        mock_tool_class.return_value.execute = AsyncMock(return_value="工具结果")

        empty_call = ToolCall(id="tc_empty", name="diagnose_resume", arguments="")
        stream_mock = MagicMock(side_effect=[
            _make_stream_response(tool_calls=[empty_call]),
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

        # 空 arguments 应被当作 {} 处理，execute 被调用
        mock_tool_class.return_value.execute.assert_called_once()


# ═══════════════════════════════════════════════════════════════
# 4. 连续 2 次坏调用强制收敛
# ═══════════════════════════════════════════════════════════════


class TestConsecutiveBadCallsConvergence:
    """A3 per-tool 重试预算：同一工具连续失败 MAX_TOOL_RETRIES 次 → 强制跳出循环。"""

    @pytest.mark.asyncio
    async def test_exactly_two_bad_calls_then_forced_convergence(self):
        """同一工具恰好 MAX_TOOL_RETRIES 次连续失败后跳出循环，强制无工具回答。"""
        from services.react_agent.loop import MAX_TOOL_RETRIES, react_loop

        assert MAX_TOOL_RETRIES == 3, "测试预期 MAX_TOOL_RETRIES=3"

        # MAX_TOOL_RETRIES 轮坏调用走中间轮流式，强制收敛走最终轮流式（tools=None）
        stream_mock = MagicMock(side_effect=[
            _make_stream_response(
                tool_calls=[_make_tool_call(name="nonexistent")],
                content="中间思考",
            )
            for _ in range(MAX_TOOL_RETRIES)
        ] + [
            _make_stream_response(content="强制收敛答案"),
        ])

        with patch("services.react_agent.loop.assemble_system_prompt", new_callable=AsyncMock) as mock_sys, \
             patch("services.react_agent.loop.check_quota", new_callable=AsyncMock) as mock_quota, \
             patch("services.react_agent.loop.llm_generate_with_tools", new_callable=AsyncMock) as mock_llm, \
             patch("services.react_agent.loop.llm_generate_with_tools_stream", stream_mock), \
             patch("services.react_agent.loop.get_tool_by_name", return_value=None), \
             patch("services.react_agent.loop.get_agent_schemas", return_value=[]), \
             patch("services.react_agent.loop.manage_l1_context") as mock_l1:

            mock_sys.return_value = "system"
            mock_quota.return_value = (True, None)
            mock_l1.side_effect = lambda msgs, **kw: msgs

            mock_llm.return_value = _make_response(content="不应到达")

            result = await react_loop(db=AsyncMock(), user_id=1, resume_id=1, question="测试")

        assert "强制收敛" in result.answer
        # 中间轮 MAX_TOOL_RETRIES 次坏调用 + 最终轮 1 次强制收敛（均走流式）
        assert stream_mock.call_count == MAX_TOOL_RETRIES + 1
        assert mock_llm.call_count == 0  # 最终轮也走流式，非流式 llm_generate_with_tools 不再调用

        # 最终轮调 LLM 时 tools=None（强制无工具）
        last_call = stream_mock.call_args_list[-1]
        assert last_call.kwargs.get("tools") is None

    @pytest.mark.asyncio
    async def test_good_call_resets_bad_counter(self):
        """一次正常工具调用重置坏调用计数器。"""
        from services.react_agent.loop import react_loop

        mock_tool_class = MagicMock()
        mock_tool_class.return_value.execute = AsyncMock(return_value="正常结果")

        # 第 1 轮：坏调用（工具不存在 → 但 get_tool_by_name 有返回值，用坏 arguments）
        # 第 2 轮：正常工具调用
        # 第 3 轮：坏调用（工具不存在）
        # 第 4 轮：直接回答
        # 坏计数器在第 2 轮被重置，所以第 3 轮不会触发强制收敛
        bad_call_1 = ToolCall(id="bad1", name="search_resume", arguments="{invalid}")
        good_call = _make_tool_call(name="search_resume", arguments={"resume_id": 1, "query": "test"})
        bad_call_2 = ToolCall(id="bad2", name="search_resume", arguments="{also_invalid}")

        stream_mock = MagicMock(side_effect=[
            _make_stream_response(tool_calls=[bad_call_1]),
            _make_stream_response(tool_calls=[good_call]),
            _make_stream_response(tool_calls=[bad_call_2]),
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
        # 4 轮全走中间轮流式（没有强制收敛，最终轮不调用）
        assert mock_llm.call_count == 0
        assert stream_mock.call_count == 4


# ═══════════════════════════════════════════════════════════════
# 5. history 参数
# ═══════════════════════════════════════════════════════════════


class TestHistoryParameter:
    """历史消息注入。"""

    @pytest.mark.asyncio
    async def test_history_messages_included(self):
        """history 参数的消息被加入 messages。"""
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

            history = [
                {"role": "user", "content": "之前的问题"},
                {"role": "assistant", "content": "之前的回答"},
            ]

            await react_loop(
                db=AsyncMock(), user_id=1, resume_id=1, question="新问题",
                history=history,
            )

        # 中间轮流式第一次调用的 messages 即完整注入后的消息
        first_call_messages = stream_mock.call_args_list[0].kwargs["messages"]
        roles = [m["role"] for m in first_call_messages]
        # system + history(user) + history(assistant) + user(新问题)
        assert roles == ["system", "user", "assistant", "user"]
        assert first_call_messages[1]["content"] == "之前的问题"
        assert first_call_messages[3]["content"] == "新问题"

    @pytest.mark.asyncio
    async def test_no_history_works(self):
        """不传 history 时正常工作。"""
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

            result = await react_loop(db=AsyncMock(), user_id=1, resume_id=1, question="测试")

        assert result.answer == "答案"


# ═══════════════════════════════════════════════════════════════
# 7. MAX_ROUNDS 读 config + 每轮 quota 复查（ /A#6 对齐）
# ═══════════════════════════════════════════════════════════════


class TestMaxRoundsAndPerRoundQuota:
    """MAX_ROUNDS 从 config 读取；每轮 LLM 调用前复查 quota。"""

    def test_max_rounds_reads_from_config(self):
        """MAX_ROUNDS 应从 config 读取（=6），非硬编码 10。"""
        from services.react_agent import loop
        from core.config import settings

        assert loop.MAX_ROUNDS == settings.REACT_MAX_TOOL_ROUNDS
        assert loop.MAX_ROUNDS == 6

    @pytest.mark.asyncio
    async def test_quota_rechecked_each_round(self):
        """第 2 轮配额耗尽 → 发 quota_exceeded，LLM 只调用 1 次。"""
        from services.react_agent.loop import react_loop

        mock_tool_class = MagicMock()
        mock_tool_class.return_value.execute = AsyncMock(return_value="结果")

        events: list[dict] = []

        async def cb(event: dict):
            events.append(event)

        stream_mock = MagicMock(side_effect=[
            _make_stream_response(tool_calls=[_make_tool_call()]),
        ])

        with patch("services.react_agent.loop.assemble_system_prompt", new_callable=AsyncMock) as mock_sys, \
             patch("services.react_agent.loop.check_quota", new_callable=AsyncMock) as mock_quota, \
             patch("services.react_agent.loop.llm_generate_with_tools", new_callable=AsyncMock) as mock_llm, \
             patch("services.react_agent.loop.llm_generate_with_tools_stream", stream_mock), \
             patch("services.react_agent.loop.get_tool_by_name", return_value=mock_tool_class), \
             patch("services.react_agent.loop.get_agent_schemas", return_value=[]), \
             patch("services.react_agent.loop.manage_l1_context") as mock_l1:

            mock_sys.return_value = "system"
            # 预检通过 → 第 2 轮复查失败
            mock_quota.side_effect = [(True, None), (False, "额度用完")]
            mock_l1.side_effect = lambda msgs, **kw: msgs
            # 第 1 轮调工具；第 2 轮不应到达（quota 先拦截）
            mock_llm.return_value = _make_response(content="不应到达")

            result = await react_loop(
                db=AsyncMock(), user_id=1, resume_id=1, question="测试",
                event_callback=cb,
            )

        types = [e["type"] for e in events]
        assert "quota_exceeded" in types
        assert mock_llm.call_count == 0  # 第 2 轮被 quota 拦截，最终轮不调用
        assert stream_mock.call_count == 1
        assert "不应到达" not in result.answer


# ═══════════════════════════════════════════════════════════════
# 8. 工具并行执行（ /A#32 对齐）
# ═══════════════════════════════════════════════════════════════


class TestParallelToolExecution:
    """一轮多个 tool_calls 用 asyncio.gather 并行执行（Spec A#21/A#32）。"""

    @pytest.mark.asyncio
    async def test_multiple_tool_calls_execute_concurrently(self):
        """一轮 2 个 tool_calls 并行执行，非串行等待。"""
        from services.react_agent.loop import react_loop

        mock_tool_class = MagicMock()
        start_times: list[float] = []

        async def tracked_execute(**kwargs):
            start_times.append(asyncio.get_event_loop().time())
            await asyncio.sleep(0.05)  # 模拟 50ms 耗时
            return "结果"

        mock_tool_class.return_value.execute = tracked_execute

        stream_mock = MagicMock(side_effect=[
            _make_stream_response(tool_calls=[
                _make_tool_call(call_id="tc_1"),
                _make_tool_call(call_id="tc_2"),
            ]),
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

        assert len(start_times) == 2
        # 并行：两个 start 时间差应远小于 0.05s（串行会 >= 0.05s）
        assert abs(start_times[1] - start_times[0]) < 0.04

    @pytest.mark.asyncio
    async def test_all_tool_call_events_before_tool_results(self):
        """并行模式：所有 tool_call 事件在 tool_result/tool_error 之前。"""
        from services.react_agent.loop import react_loop

        mock_tool_class = MagicMock()
        mock_tool_class.return_value.execute = AsyncMock(return_value="结果")

        events_received: list[dict] = []

        async def callback(event: dict):
            events_received.append(event)

        stream_mock = MagicMock(side_effect=[
            _make_stream_response(tool_calls=[
                _make_tool_call(call_id="tc_1", name="search_resume"),
                _make_tool_call(call_id="tc_2", name="diagnose_resume"),
            ]),
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

            await react_loop(
                db=AsyncMock(), user_id=1, resume_id=1, question="测试",
                event_callback=callback,
            )

        types = [e["type"] for e in events_received]
        first_result_idx = next(
            (i for i, t in enumerate(types) if t in ("tool_result", "tool_error")),
            len(types),
        )
        calls_before = [t for t in types[:first_result_idx] if t == "tool_call"]
        assert len(calls_before) == 2

    @pytest.mark.asyncio
    async def test_parallel_one_error_one_success(self):
        """并行执行中一个失败一个成功 → all_bad=False，不触发强制收敛。"""
        from services.react_agent.loop import react_loop

        def get_tool_mock(name):
            if name == "nonexistent":
                return None
            mock = MagicMock()
            mock.return_value.execute = AsyncMock(return_value="正常结果")
            return mock

        events_received: list[dict] = []

        async def callback(event: dict):
            events_received.append(event)

        stream_mock = MagicMock(side_effect=[
            _make_stream_response(tool_calls=[
                _make_tool_call(call_id="tc_1", name="nonexistent"),
                _make_tool_call(call_id="tc_2", name="search_resume"),
            ]),
            _make_stream_response(content="最终答案"),
        ])

        with patch("services.react_agent.loop.assemble_system_prompt", new_callable=AsyncMock) as mock_sys, \
             patch("services.react_agent.loop.check_quota", new_callable=AsyncMock) as mock_quota, \
             patch("services.react_agent.loop.llm_generate_with_tools", new_callable=AsyncMock) as mock_llm, \
             patch("services.react_agent.loop.llm_generate_with_tools_stream", stream_mock), \
             patch("services.react_agent.loop.get_tool_by_name", side_effect=get_tool_mock), \
             patch("services.react_agent.loop.get_agent_schemas", return_value=[]), \
             patch("services.react_agent.loop.manage_l1_context") as mock_l1:

            mock_sys.return_value = "system"
            mock_quota.return_value = (True, None)
            mock_l1.side_effect = lambda msgs, **kw: msgs

            mock_llm.return_value = _make_response(content="不应到达")

            result = await react_loop(
                db=AsyncMock(), user_id=1, resume_id=1, question="测试",
                event_callback=callback,
            )

        types = [e["type"] for e in events_received]
        assert "tool_error" in types
        assert "tool_result" in types
        assert "最终答案" in result.answer

    @pytest.mark.asyncio
    async def test_parallel_tools_messages_correctly_appended(self):
        """并行工具的结果正确回灌到 messages（2 个 tool 消息）。"""
        from services.react_agent.loop import react_loop

        mock_tool_class = MagicMock()
        mock_tool_class.return_value.execute = AsyncMock(return_value="工具结果")

        stream_mock = MagicMock(side_effect=[
            _make_stream_response(tool_calls=[
                _make_tool_call(call_id="tc_1"),
                _make_tool_call(call_id="tc_2"),
            ]),
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

        # 第二轮（中间轮流式）的 messages 应包含 2 条 tool 回灌
        second_call_msgs = stream_mock.call_args_list[1].kwargs["messages"]
        tool_msgs = [m for m in second_call_msgs if m.get("role") == "tool"]
        assert len(tool_msgs) == 2
        tool_ids = {m["tool_call_id"] for m in tool_msgs}
        assert tool_ids == {"tc_1", "tc_2"}


# ═══════════════════════════════════════════════════════════════
# 9. agent_thought + usage 事件分拣（ /A#28 对齐）
# ═══════════════════════════════════════════════════════════════


class TestAgentThoughtAndUsageEvents:
    """agent_thought（推理内容）和 usage（token 消耗）事件分拣。"""

    @pytest.mark.asyncio
    async def test_agent_thought_emitted_when_reasoning_exists(self):
        """LLM 返回 reasoning_content → 发 agent_thought 事件。"""
        from services.react_agent.loop import react_loop

        mock_tool_class = MagicMock()
        mock_tool_class.return_value.execute = AsyncMock(return_value="结果")

        events: list[dict] = []

        async def cb(event: dict):
            events.append(event)

        # 中间轮流式：第一轮产出 reasoning（实时 emit agent_thought）
        stream_mock = MagicMock(side_effect=[
            _make_stream_response(
                tool_calls=[_make_tool_call()],
                reasoning="让我想想应该用什么工具...",
            ),
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

            await react_loop(
                db=AsyncMock(), user_id=1, resume_id=1, question="测试",
                event_callback=cb,
            )

        thought_events = [e for e in events if e["type"] == "agent_thought"]
        assert len(thought_events) == 1
        # 对外只发可读阶段提示，不泄露 provider 的原始思维链。
        assert thought_events[0]["content"] == "正在分析需求并规划下一步"

    @pytest.mark.asyncio
    async def test_agent_thought_not_emitted_when_no_reasoning(self):
        """LLM 返回 reasoning_content=None → 不发 agent_thought。"""
        from services.react_agent.loop import react_loop

        mock_tool_class = MagicMock()
        mock_tool_class.return_value.execute = AsyncMock(return_value="结果")

        events: list[dict] = []

        async def cb(event: dict):
            events.append(event)

        # 中间轮流式无 reasoning → 不 emit agent_thought
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

            await react_loop(
                db=AsyncMock(), user_id=1, resume_id=1, question="测试",
                event_callback=cb,
            )

        thought_events = [e for e in events if e["type"] == "agent_thought"]
        assert len(thought_events) == 0

    @pytest.mark.asyncio
    async def test_usage_event_emitted_after_each_llm_call(self):
        """每次 LLM 调用后发 usage 事件，含本次 token 和累计。"""
        from services.react_agent.loop import react_loop

        mock_tool_class = MagicMock()
        mock_tool_class.return_value.execute = AsyncMock(return_value="结果")
        mock_tool_class.return_value.last_usage = {"prompt_tokens": 0, "completion_tokens": 0}
        mock_tool_class.return_value.sources = []

        events: list[dict] = []

        async def cb(event: dict):
            events.append(event)

        # 两轮中间轮流式，usage 事件分别 200/80 和 150/60
        stream_mock = MagicMock(side_effect=[
            _make_stream_response(
                tool_calls=[_make_tool_call()],
                usage={"prompt_tokens": 200, "completion_tokens": 80},
            ),
            _make_stream_response(
                content="最终答案",
                usage={"prompt_tokens": 150, "completion_tokens": 60},
            ),
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

            await react_loop(
                db=AsyncMock(), user_id=1, resume_id=1, question="测试",
                event_callback=cb,
            )

        usage_events = [e for e in events if e["type"] == "usage"]
        # 2 轮中间轮 + 1 次工具执行后 → 3 个 usage 事件
        assert len(usage_events) == 3
        # 第一个 usage 事件（LLM round 1）：本次 200+80，累计 200+80
        assert usage_events[0]["usage"]["prompt_tokens"] == 200
        assert usage_events[0]["total"]["prompt_tokens"] == 200
        # 第二个 usage 事件（工具执行后）：累计仍为 200+80（工具无内部 LLM）
        assert usage_events[1]["total"]["prompt_tokens"] == 200
        # 第三个 usage 事件（LLM round 2）：本次 150+60，累计 350+140
        assert usage_events[2]["usage"]["prompt_tokens"] == 150
        assert usage_events[2]["total"]["prompt_tokens"] == 350

    @pytest.mark.asyncio
    async def test_usage_event_not_emitted_when_quota_exceeded(self):
        """配额不足时不发 usage 事件（没调 LLM）。"""
        from services.react_agent.loop import react_loop

        events: list[dict] = []

        async def cb(event: dict):
            events.append(event)

        with patch("services.react_agent.loop.assemble_system_prompt", new_callable=AsyncMock), \
             patch("services.react_agent.loop.check_quota", new_callable=AsyncMock) as mock_quota, \
             patch("services.react_agent.loop.llm_generate_with_tools", new_callable=AsyncMock) as mock_llm, \
             patch("services.react_agent.loop.get_agent_schemas", return_value=[]):

            mock_quota.return_value = (False, "额度用完")

            await react_loop(
                db=AsyncMock(), user_id=1, resume_id=1, question="测试",
                event_callback=cb,
            )

        usage_events = [e for e in events if e["type"] == "usage"]
        assert len(usage_events) == 0
        mock_llm.assert_not_called()


# ═══════════════════════════════════════════════════════════════
# 10. sources 聚合（ : search_resume 来源去重进 done.sources）
# ═══════════════════════════════════════════════════════════════


class TestSourcesAggregation:
    """search_resume 工具的结构化来源聚合到 result.sources。"""

    @pytest.mark.asyncio
    async def test_sources_collected_from_tool_with_sources(self):
        """工具执行后 tool.sources 被收集到 result.sources。"""
        from services.react_agent.loop import react_loop

        mock_tool_instance = MagicMock()
        mock_tool_instance.sources = [
            {"section": "工作经历", "text": "在ABC公司工作", "score": 0.9},
        ]
        mock_tool_instance.execute = AsyncMock(return_value="检索结果")
        mock_tool_class = MagicMock(return_value=mock_tool_instance)

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

            mock_sys.return_value = "system"
            mock_quota.return_value = (True, None)
            mock_l1.side_effect = lambda msgs, **kw: msgs

            mock_llm.return_value = _make_response(content="不应到达")

            result = await react_loop(db=AsyncMock(), user_id=1, resume_id=1, question="测试")

        assert hasattr(result, "sources")
        assert len(result.sources) == 1
        assert result.sources[0]["section"] == "工作经历"

    @pytest.mark.asyncio
    async def test_sources_empty_when_tool_has_no_sources(self):
        """工具没有 sources 属性时 result.sources 为空列表。"""
        from services.react_agent.loop import react_loop

        mock_tool_class = MagicMock()
        mock_tool_class.return_value.execute = AsyncMock(return_value="结果")
        # 不设置 sources 属性

        stream_mock = MagicMock(side_effect=[
            _make_stream_response(tool_calls=[_make_tool_call(name="diagnose_resume")]),
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

        assert hasattr(result, "sources")
        assert result.sources == []

    @pytest.mark.asyncio
    async def test_sources_deduplicated_across_rounds(self):
        """多轮 search_resume 调用的来源按 text 去重。"""
        from services.react_agent.loop import react_loop

        # 两个 mock tool 实例（两轮调用），有重叠的 source
        source_a = {"section": "工作经历", "text": "在ABC公司工作", "score": 0.9}
        source_b = {"section": "教育背景", "text": "毕业于XYZ大学", "score": 0.8}
        source_dup = {"section": "工作经历", "text": "在ABC公司工作", "score": 0.85}  # 与 a 重复

        # 第一轮 tool 有 source_a + source_b
        mock_tool_1 = MagicMock()
        mock_tool_1.sources = [source_a, source_b]
        mock_tool_1.execute = AsyncMock(return_value="结果1")

        # 第二轮 tool 有 source_dup（与 source_a text 相同）
        mock_tool_2 = MagicMock()
        mock_tool_2.sources = [source_dup]
        mock_tool_2.execute = AsyncMock(return_value="结果2")

        # get_tool_by_name 每次返回不同实例
        call_count = [0]
        def get_tool_mock(name):
            call_count[0] += 1
            return MagicMock(return_value=mock_tool_1 if call_count[0] == 1 else mock_tool_2)

        stream_mock = MagicMock(side_effect=[
            _make_stream_response(tool_calls=[_make_tool_call(name="search_resume", call_id="tc_1")]),
            _make_stream_response(tool_calls=[_make_tool_call(name="search_resume", call_id="tc_2")]),
            _make_stream_response(content="最终答案"),
        ])

        with patch("services.react_agent.loop.assemble_system_prompt", new_callable=AsyncMock) as mock_sys, \
             patch("services.react_agent.loop.check_quota", new_callable=AsyncMock) as mock_quota, \
             patch("services.react_agent.loop.llm_generate_with_tools", new_callable=AsyncMock) as mock_llm, \
             patch("services.react_agent.loop.llm_generate_with_tools_stream", stream_mock), \
             patch("services.react_agent.loop.get_tool_by_name", side_effect=get_tool_mock), \
             patch("services.react_agent.loop.get_agent_schemas", return_value=[]), \
             patch("services.react_agent.loop.manage_l1_context") as mock_l1:

            mock_sys.return_value = "system"
            mock_quota.return_value = (True, None)
            mock_l1.side_effect = lambda msgs, **kw: msgs

            mock_llm.return_value = _make_response(content="不应到达")

            result = await react_loop(db=AsyncMock(), user_id=1, resume_id=1, question="测试")

        # 3 个 source 输入，1 个重复 → 2 个去重后
        assert len(result.sources) == 2
        texts = {s["text"] for s in result.sources}
        assert "在ABC公司工作" in texts
        assert "毕业于XYZ大学" in texts

    @pytest.mark.asyncio
    async def test_sources_from_multiple_tools_in_one_round(self):
        """一轮并行执行多个工具，各自的 sources 都被收集。"""
        from services.react_agent.loop import react_loop

        # Tool 1 有 sources
        mock_tool_1 = MagicMock()
        mock_tool_1.sources = [{"section": "技能", "text": "Python", "score": 0.95}]
        mock_tool_1.execute = AsyncMock(return_value="结果1")

        # Tool 2 也有 sources
        mock_tool_2 = MagicMock()
        mock_tool_2.sources = [{"section": "项目", "text": "AI Agent", "score": 0.88}]
        mock_tool_2.execute = AsyncMock(return_value="结果2")

        def get_tool_mock(name):
            if name == "search_resume":
                return MagicMock(return_value=mock_tool_1)
            return MagicMock(return_value=mock_tool_2)

        stream_mock = MagicMock(side_effect=[
            _make_stream_response(tool_calls=[
                _make_tool_call(name="search_resume", call_id="tc_1"),
                _make_tool_call(name="other_tool", call_id="tc_2"),
            ]),
            _make_stream_response(content="最终答案"),
        ])

        with patch("services.react_agent.loop.assemble_system_prompt", new_callable=AsyncMock) as mock_sys, \
             patch("services.react_agent.loop.check_quota", new_callable=AsyncMock) as mock_quota, \
             patch("services.react_agent.loop.llm_generate_with_tools", new_callable=AsyncMock) as mock_llm, \
             patch("services.react_agent.loop.llm_generate_with_tools_stream", stream_mock), \
             patch("services.react_agent.loop.get_tool_by_name", side_effect=get_tool_mock), \
             patch("services.react_agent.loop.get_agent_schemas", return_value=[]), \
             patch("services.react_agent.loop.manage_l1_context") as mock_l1:

            mock_sys.return_value = "system"
            mock_quota.return_value = (True, None)
            mock_l1.side_effect = lambda msgs, **kw: msgs

            mock_llm.return_value = _make_response(content="不应到达")

            result = await react_loop(db=AsyncMock(), user_id=1, resume_id=1, question="测试")

        assert len(result.sources) == 2


# ═══════════════════════════════════════════════════════════════
# 11. db_trace 完整 prompt 持久化（Spec: 完整 prompt 进 DB）
# ═══════════════════════════════════════════════════════════════


class TestDbTraceCapture:
    """react_loop 捕获完整 prompt 信息到 result.db_trace（Spec 行 459/482）。

    DB 存完整 prompt（system + 记忆注入 + 工具序列 + 模型），
    SSE done 事件只发紧凑摘要（轮数/工具序列/耗时）。
    """

    @pytest.mark.asyncio
    async def test_db_trace_exists_on_result(self):
        """ReactLoopResult 有 db_trace 字段。"""
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

            result = await react_loop(db=AsyncMock(), user_id=1, resume_id=1, question="测试")

        assert hasattr(result, "db_trace")
        assert isinstance(result.db_trace, dict)

    @pytest.mark.asyncio
    async def test_db_trace_captures_system_prompt(self):
        """db_trace 包含组装后的 system_prompt。"""
        from services.react_agent.loop import react_loop

        stream_mock = MagicMock(side_effect=[_make_stream_response(content="答案")])

        with patch("services.react_agent.loop.assemble_system_prompt", new_callable=AsyncMock) as mock_sys, \
             patch("services.react_agent.loop.check_quota", new_callable=AsyncMock) as mock_quota, \
             patch("services.react_agent.loop.llm_generate_with_tools", new_callable=AsyncMock) as mock_llm, \
             patch("services.react_agent.loop.llm_generate_with_tools_stream", stream_mock), \
             patch("services.react_agent.loop.get_agent_schemas", return_value=[]), \
             patch("services.react_agent.loop.manage_l1_context") as mock_l1:

            mock_sys.return_value = "你是简历助手，以下是用户画像：3年Python后端"
            mock_quota.return_value = (True, None)
            mock_l1.side_effect = lambda msgs, **kw: msgs
            mock_llm.return_value = _make_response(content="不应到达")

            result = await react_loop(db=AsyncMock(), user_id=1, resume_id=1, question="测试")

        assert "system_prompt" in result.db_trace
        assert "简历助手" in result.db_trace["system_prompt"]

    @pytest.mark.asyncio
    async def test_db_trace_captures_model_per_round(self):
        """db_trace 记录每轮使用的模型（中间轮 judge，最终轮 chat）。"""
        from services.react_agent.loop import react_loop, MIDDLE_MODEL

        mock_tool_class = MagicMock()
        mock_tool_class.return_value.execute = AsyncMock(return_value="结果")

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

        rounds = result.db_trace.get("rounds", [])
        assert len(rounds) >= 1
        # 第一轮应记录模型
        assert "model" in rounds[0]
        assert rounds[0]["model"] == MIDDLE_MODEL

    @pytest.mark.asyncio
    async def test_db_trace_captures_tool_sequence(self):
        """db_trace 记录工具调用序列（name + arguments）。"""
        from services.react_agent.loop import react_loop

        mock_tool_class = MagicMock()
        mock_tool_class.return_value.execute = AsyncMock(return_value="结果")

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

            mock_sys.return_value = "system"
            mock_quota.return_value = (True, None)
            mock_l1.side_effect = lambda msgs, **kw: msgs

            mock_llm.return_value = _make_response(content="不应到达")

            result = await react_loop(db=AsyncMock(), user_id=1, resume_id=1, question="测试")

        rounds = result.db_trace.get("rounds", [])
        assert len(rounds) >= 1
        tool_calls = rounds[0].get("tool_calls", [])
        assert len(tool_calls) == 1
        assert tool_calls[0]["name"] == "search_resume"

    @pytest.mark.asyncio
    async def test_db_trace_captures_total_rounds(self):
        """db_trace 记录总轮数。"""
        from services.react_agent.loop import react_loop

        mock_tool_class = MagicMock()
        mock_tool_class.return_value.execute = AsyncMock(return_value="结果")

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

        assert "total_rounds" in result.db_trace
        assert result.db_trace["total_rounds"] == 1  # 1 轮工具 + 1 轮回答 = 1 轮工具调用轮


# ═══════════════════════════════════════════════════════════════
# 8. builder 模式接线
# ═══════════════════════════════════════════════════════════════


class TestBuilderModeWiring:
    """tool_mode='builder' 时统一工具集 schema 传给流式 LLM。"""

    @pytest.mark.asyncio
    async def test_builder_mode_passes_builder_schemas_to_llm(self):
        from services.react_agent.loop import react_loop

        stream_mock = MagicMock(side_effect=[_make_stream_response(content="答案")])

        # mock builder 工具类：实例 to_openai_schema 返回固定 schema
        mock_tool_class = MagicMock()
        mock_tool_class.name = "generate_module"
        mock_tool_class.return_value.to_openai_schema.return_value = {"dummy": 1}

        with patch("services.react_agent.loop.assemble_system_prompt", new_callable=AsyncMock) as mock_sys, \
             patch("services.react_agent.loop.check_quota", new_callable=AsyncMock) as mock_quota, \
             patch("services.react_agent.loop.llm_generate_with_tools", new_callable=AsyncMock) as mock_llm, \
             patch("services.react_agent.loop.llm_generate_with_tools_stream", stream_mock), \
             patch("services.react_agent.builder_intent.resolve_builder_intent", new_callable=AsyncMock) as mock_intent, \
             patch("services.react_agent.loop.get_tools_for_agent", return_value=[mock_tool_class]), \
             patch("services.react_agent.loop.get_agent_schemas", return_value=[]), \
             patch("services.react_agent.loop.manage_l1_context") as mock_l1:

            mock_sys.return_value = "system"
            mock_quota.return_value = (True, None)
            mock_l1.side_effect = lambda msgs, **kw: msgs
            mock_llm.return_value = _make_response(content="不应到达")
            mock_intent.return_value = None  # 无明确编辑意图 → 回退 ReAct 循环

            result = await react_loop(
                db=AsyncMock(), user_id=1, resume_id=1,
                question="测试", tool_mode="builder",
            )

        # builder 工具 schema 传给中间轮流式调用
        captured_tools = stream_mock.call_args_list[0].kwargs["tools"]
        assert captured_tools == [{"dummy": 1}]
        assert result.answer == "答案"
