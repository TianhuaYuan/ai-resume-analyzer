"""streaming SSE + /ask/agent 测试。

测试范围：
1. SSE 事件序列化：react_loop_stream 产出正确的事件类型和内容
2. 占位记录：流开始时创建 status=streaming 的 QA 记录
3. 完成更新：流结束时更新 answer + status=complete
4. 配额检查：配额不足时返回 quota_exceeded 事件
5. 断连处理：CancelledError 时占位记录保留
6. process_trace 双载荷：SSE 推紧凑摘要，DB 存完整 prompt（Spec 行 459/482）
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.rag.pipeline import LLMToolResponse, ToolCall


# ── 辅助函数 ──────────────────────────────────────────────────


def _make_response(content="", tool_calls=None, usage=None):
    return LLMToolResponse(
        content=content,
        tool_calls=tool_calls or [],
        reasoning_content=None,
        usage=usage or {"prompt_tokens": 100, "completion_tokens": 50},
    )


def _make_tool_call(name="search_resume", arguments=None, call_id="tc_1"):
    return ToolCall(
        id=call_id,
        name=name,
        arguments=json.dumps(arguments or {"resume_id": 1, "query": "test"}),
    )


def _make_stream_response(content="", tool_calls=None, usage=None):
    """构造模拟 llm_generate_with_tools_stream 的 async generator。

    中间轮改流式后，react_loop 通过 _stream_middle_round 消费该流。
    async generator 不可复用，多轮需各自生成独立实例。
    """
    async def _gen():
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


def _make_mock_tool_class(result="工具结果"):
    mock_tool = MagicMock()
    mock_tool.execute = AsyncMock(return_value=result)
    # 工具内部 LLM 消耗与来源必须是真实值，否则 _accumulate_usage 会把 MagicMock
    # 累加进 usage，streaming.py 的 pt > 0 比较会抛 TypeError
    mock_tool.last_usage = {"prompt_tokens": 0, "completion_tokens": 0}
    mock_tool.sources = []
    return MagicMock(return_value=mock_tool)


def _patch_loop_deps():
    """批量 patch loop 依赖。"""
    return {
        "llm": patch("services.react_agent.loop.llm_generate_with_tools", new_callable=AsyncMock),
        "sys": patch("services.react_agent.loop.assemble_system_prompt", new_callable=AsyncMock),
        "quota": patch("services.react_agent.loop.check_quota", new_callable=AsyncMock),
        "l1": patch("services.react_agent.loop.manage_l1_context"),
        "get_tool": patch("services.react_agent.loop.get_tool_by_name"),
        "schemas": patch("services.react_agent.loop.get_agent_schemas"),
    }


# ═══════════════════════════════════════════════════════════════
# 1. SSE 事件序列化
# ═══════════════════════════════════════════════════════════════


class TestSSEEventSerialization:
    """react_loop_stream 产出正确的 SSE 事件序列。"""

    @pytest.mark.asyncio
    async def test_direct_answer_events(self):
        """LLM 直接回答 → agent_start + agent_done。"""
        from services.react_agent.streaming import react_loop_stream

        stream_mock = MagicMock(side_effect=[_make_stream_response(content="最终答案")])

        with patch("services.react_agent.loop.assemble_system_prompt", new_callable=AsyncMock) as mock_sys, \
             patch("services.react_agent.loop.check_quota", new_callable=AsyncMock) as mock_quota, \
             patch("services.react_agent.loop.llm_generate_with_tools", new_callable=AsyncMock) as mock_llm, \
             patch("services.react_agent.loop.llm_generate_with_tools_stream", stream_mock), \
             patch("services.react_agent.loop.get_agent_schemas", return_value=[]), \
             patch("services.react_agent.loop.manage_l1_context") as mock_l1, \
             patch("services.react_agent.streaming.save_qa_placeholder", new_callable=AsyncMock) as mock_save, \
             patch("services.react_agent.streaming.update_qa_answer", new_callable=AsyncMock) as mock_update:

            mock_sys.return_value = "system"
            mock_quota.return_value = (True, None)
            mock_l1.side_effect = lambda msgs, **kw: msgs
            mock_llm.return_value = _make_response(content="不应到达")
            mock_save.return_value = MagicMock(id=42)
            mock_update.return_value = MagicMock(id=42)

            events = []
            async for event in react_loop_stream(
                db=AsyncMock(), user_id=1, resume_id=1, question="测试",
            ):
                events.append(event)

        types = [e["type"] for e in events]
        assert "agent_start" in types
        assert "agent_done" in types
        # agent_done 应包含 answer
        done_event = next(e for e in events if e["type"] == "agent_done")
        assert "最终答案" in done_event["answer"]

    @pytest.mark.asyncio
    async def test_tool_call_events(self):
        """工具调用 → agent_start + tool_call + tool_result + agent_done。"""
        from services.react_agent.streaming import react_loop_stream

        mock_tool_class = _make_mock_tool_class(result="检索到 3 条经历")

        stream_mock = MagicMock(side_effect=[
            _make_stream_response(tool_calls=[_make_tool_call(name="search_resume")]),
            _make_stream_response(content="根据检索结果回答"),
        ])

        with patch("services.react_agent.loop.assemble_system_prompt", new_callable=AsyncMock) as mock_sys, \
             patch("services.react_agent.loop.check_quota", new_callable=AsyncMock) as mock_quota, \
             patch("services.react_agent.loop.llm_generate_with_tools", new_callable=AsyncMock) as mock_llm, \
             patch("services.react_agent.loop.llm_generate_with_tools_stream", stream_mock), \
             patch("services.react_agent.loop.get_tool_by_name", return_value=mock_tool_class), \
             patch("services.react_agent.loop.get_agent_schemas", return_value=[]), \
             patch("services.react_agent.loop.manage_l1_context") as mock_l1, \
             patch("services.react_agent.streaming.save_qa_placeholder", new_callable=AsyncMock) as mock_save, \
             patch("services.react_agent.streaming.update_qa_answer", new_callable=AsyncMock):

            mock_sys.return_value = "system"
            mock_quota.return_value = (True, None)
            mock_l1.side_effect = lambda msgs, **kw: msgs
            mock_llm.return_value = _make_response(content="不应到达")
            mock_save.return_value = MagicMock(id=42)

            events = []
            async for event in react_loop_stream(
                db=AsyncMock(), user_id=1, resume_id=1, question="我的经历",
            ):
                events.append(event)

        types = [e["type"] for e in events]
        assert "tool_call" in types
        assert "tool_result" in types
        assert "agent_done" in types

        tool_call_event = next(e for e in events if e["type"] == "tool_call")
        assert tool_call_event["tool_name"] == "search_resume"

        tool_result_event = next(e for e in events if e["type"] == "tool_result")
        assert "检索到 3 条经历" in tool_result_event["detail"]


# ═══════════════════════════════════════════════════════════════
# 2. 占位记录
# ═══════════════════════════════════════════════════════════════


class TestPlaceholderRecord:
    """流开始时创建 status=streaming 的占位记录。"""

    @pytest.mark.asyncio
    async def test_placeholder_created_at_start(self):
        """agent_start 事件前创建占位记录。"""
        from services.react_agent.streaming import react_loop_stream

        stream_mock = MagicMock(side_effect=[_make_stream_response(content="答案")])

        with patch("services.react_agent.loop.assemble_system_prompt", new_callable=AsyncMock) as mock_sys, \
             patch("services.react_agent.loop.check_quota", new_callable=AsyncMock) as mock_quota, \
             patch("services.react_agent.loop.llm_generate_with_tools", new_callable=AsyncMock) as mock_llm, \
             patch("services.react_agent.loop.llm_generate_with_tools_stream", stream_mock), \
             patch("services.react_agent.loop.get_agent_schemas", return_value=[]), \
             patch("services.react_agent.loop.manage_l1_context") as mock_l1, \
             patch("services.react_agent.streaming.save_qa_placeholder", new_callable=AsyncMock) as mock_save, \
             patch("services.react_agent.streaming.update_qa_answer", new_callable=AsyncMock) as mock_update:

            mock_sys.return_value = "system"
            mock_quota.return_value = (True, None)
            mock_l1.side_effect = lambda msgs, **kw: msgs
            mock_llm.return_value = _make_response(content="不应到达")
            mock_save.return_value = MagicMock(id=99)
            mock_update.return_value = MagicMock(id=99)

            events = []
            async for event in react_loop_stream(
                db=AsyncMock(), user_id=1, resume_id=1, question="测试",
            ):
                events.append(event)

        # 占位记录已创建
        mock_save.assert_called_once()
        save_kwargs = mock_save.call_args
        assert save_kwargs.kwargs.get("user_id") == 1 or save_kwargs.args[1] == 1

        # 完成后更新了记录
        mock_update.assert_called_once()

    @pytest.mark.asyncio
    async def test_done_event_contains_qa_id(self):
        """agent_done 事件包含 qa_id。"""
        from services.react_agent.streaming import react_loop_stream

        stream_mock = MagicMock(side_effect=[_make_stream_response(content="答案")])

        with patch("services.react_agent.loop.assemble_system_prompt", new_callable=AsyncMock) as mock_sys, \
             patch("services.react_agent.loop.check_quota", new_callable=AsyncMock) as mock_quota, \
             patch("services.react_agent.loop.llm_generate_with_tools", new_callable=AsyncMock) as mock_llm, \
             patch("services.react_agent.loop.llm_generate_with_tools_stream", stream_mock), \
             patch("services.react_agent.loop.get_agent_schemas", return_value=[]), \
             patch("services.react_agent.loop.manage_l1_context") as mock_l1, \
             patch("services.react_agent.streaming.save_qa_placeholder", new_callable=AsyncMock) as mock_save, \
             patch("services.react_agent.streaming.update_qa_answer", new_callable=AsyncMock):

            mock_sys.return_value = "system"
            mock_quota.return_value = (True, None)
            mock_l1.side_effect = lambda msgs, **kw: msgs
            mock_llm.return_value = _make_response(content="不应到达")
            mock_save.return_value = MagicMock(id=77)

            events = []
            async for event in react_loop_stream(
                db=AsyncMock(), user_id=1, resume_id=1, question="测试",
            ):
                events.append(event)

        done_event = next(e for e in events if e["type"] == "agent_done")
        assert done_event["qa_id"] == 77


# ═══════════════════════════════════════════════════════════════
# 3. 配额检查
# ═══════════════════════════════════════════════════════════════


class TestStreamingQuotaCheck:
    """配额不足时返回 quota_exceeded 事件。"""

    @pytest.mark.asyncio
    async def test_quota_exceeded_event(self):
        """配额不足 → 只产出 quota_exceeded 事件。"""
        from services.react_agent.streaming import react_loop_stream

        with patch("services.react_agent.loop.assemble_system_prompt", new_callable=AsyncMock) as mock_sys, \
             patch("services.react_agent.loop.check_quota", new_callable=AsyncMock) as mock_quota, \
             patch("services.react_agent.loop.llm_generate_with_tools", new_callable=AsyncMock) as mock_llm, \
             patch("services.react_agent.loop.get_agent_schemas", return_value=[]), \
             patch("services.react_agent.streaming.save_qa_placeholder", new_callable=AsyncMock) as mock_save, \
             patch("services.react_agent.streaming.update_qa_answer", new_callable=AsyncMock):

            mock_sys.return_value = "system"
            mock_quota.return_value = (False, "今日额度已用完")

            events = []
            async for event in react_loop_stream(
                db=AsyncMock(), user_id=1, resume_id=1, question="测试",
            ):
                events.append(event)

        types = [e["type"] for e in events]
        assert "quota_exceeded" in types
        assert "agent_done" not in types
        mock_llm.assert_not_called()
        mock_save.assert_not_called()


# ═══════════════════════════════════════════════════════════════
# 4. 坏 tool_call 事件
# ═══════════════════════════════════════════════════════════════


class TestStreamingToolError:
    """坏 tool_call 在 SSE 中产出 tool_error 事件。"""

    @pytest.mark.asyncio
    async def test_tool_error_event(self):
        """工具不存在 → tool_error 事件。"""
        from services.react_agent.streaming import react_loop_stream

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
             patch("services.react_agent.loop.manage_l1_context") as mock_l1, \
             patch("services.react_agent.streaming.save_qa_placeholder", new_callable=AsyncMock) as mock_save, \
             patch("services.react_agent.streaming.update_qa_answer", new_callable=AsyncMock):

            mock_sys.return_value = "system"
            mock_quota.return_value = (True, None)
            mock_l1.side_effect = lambda msgs, **kw: msgs
            mock_llm.return_value = _make_response(content="不应到达")
            mock_save.return_value = MagicMock(id=42)

            events = []
            async for event in react_loop_stream(
                db=AsyncMock(), user_id=1, resume_id=1, question="测试",
            ):
                events.append(event)

        types = [e["type"] for e in events]
        assert "tool_error" in types

        error_event = next(e for e in events if e["type"] == "tool_error")
        assert "bad_tool" in error_event.get("tool_name", "") or "bad_tool" in error_event.get("error", "")

    @pytest.mark.asyncio
    async def test_business_failure_is_tool_error_and_degrades_final_result(self):
        """ToolFailed 不得伪装成 tool_result，最终回答必须标记降级。"""
        from services.react_agent.streaming import react_loop_stream
        from services.react_agent.tools.base import ToolFailed

        mock_tool = MagicMock()
        mock_tool.execute = AsyncMock(side_effect=ToolFailed("简历不存在或无权访问"))
        mock_tool.last_usage = {"prompt_tokens": 0, "completion_tokens": 0}
        mock_tool.sources = []
        mock_tool_class = MagicMock(return_value=mock_tool)
        stream_mock = MagicMock(side_effect=[
            _make_stream_response(tool_calls=[_make_tool_call(name="failed_tool")]),
            _make_stream_response(content="已换用其他路径回答"),
        ])

        with patch("services.react_agent.loop.assemble_system_prompt", new_callable=AsyncMock) as mock_sys, \
             patch("services.react_agent.loop.check_quota", new_callable=AsyncMock) as mock_quota, \
             patch("services.react_agent.loop.llm_generate_with_tools", new_callable=AsyncMock), \
             patch("services.react_agent.loop.llm_generate_with_tools_stream", stream_mock), \
             patch("services.react_agent.loop.get_tool_by_name", return_value=mock_tool_class), \
             patch("services.react_agent.loop.get_agent_schemas", return_value=[]), \
             patch("services.react_agent.loop.manage_l1_context") as mock_l1, \
             patch("services.react_agent.streaming._load_conversation_history", new_callable=AsyncMock, return_value=[]), \
             patch("services.react_agent.streaming.save_qa_placeholder", new_callable=AsyncMock) as mock_save, \
             patch("services.react_agent.streaming.update_qa_answer", new_callable=AsyncMock):
            mock_sys.return_value = "system"
            mock_quota.return_value = (True, None)
            mock_l1.side_effect = lambda msgs, **kw: msgs
            mock_save.return_value = MagicMock(id=42)

            events = []
            async for event in react_loop_stream(
                db=AsyncMock(), user_id=1, resume_id=1, question="测试",
            ):
                events.append(event)

        types = [e["type"] for e in events]
        assert "tool_error" in types
        assert "tool_result" not in types
        error_event = next(e for e in events if e["type"] == "tool_error")
        assert error_event["retryable"] is False
        done_event = next(e for e in events if e["type"] == "agent_done")
        assert done_event["degraded"] is True
        assert done_event["answer"] == "已换用其他路径回答"

    @pytest.mark.asyncio
    async def test_builder_intent_tool_failed_keeps_non_retryable_semantics(self):
        """Builder 意图直达不得在独立事件分支丢失 ToolFailed 语义。"""
        from services.react_agent.streaming import react_loop_stream
        from services.react_agent.tools.base import ToolFailed

        mock_tool = MagicMock()
        mock_tool.is_approval_required.return_value = False
        mock_tool.execute = AsyncMock(side_effect=ToolFailed("目标模块不存在"))
        mock_tool.last_usage = {"prompt_tokens": 0, "completion_tokens": 0}
        mock_tool.sources = []
        mock_tool_class = MagicMock(return_value=mock_tool)
        mock_tool_class.name = "failed_builder_tool"
        mock_tool_class.category = "builder"
        mock_tool.to_openai_schema.return_value = {"type": "function"}

        tool_session_context = MagicMock()
        tool_session_context.__aenter__ = AsyncMock(return_value=AsyncMock())
        tool_session_context.__aexit__ = AsyncMock(return_value=False)

        with patch("services.react_agent.loop.assemble_system_prompt", new_callable=AsyncMock) as mock_sys, \
             patch("services.react_agent.loop.check_quota", new_callable=AsyncMock) as mock_quota, \
             patch("services.react_agent.builder_intent.resolve_builder_intent", new_callable=AsyncMock) as mock_intent, \
             patch("services.react_agent.loop.get_tools_for_agent", return_value=[mock_tool_class]), \
             patch("services.react_agent.loop.get_tool_by_name", return_value=mock_tool_class), \
             patch("services.react_agent.loop.AsyncSessionLocal", return_value=tool_session_context), \
             patch("services.react_agent.loop._auth_gate.is_blocked", return_value=False), \
             patch("services.react_agent.loop._auth_gate.authorize", new_callable=AsyncMock, return_value=(True, "ok")), \
             patch("services.react_agent.loop._auth_gate.release", new_callable=AsyncMock), \
             patch("services.react_agent.streaming._load_conversation_history", new_callable=AsyncMock, return_value=[]), \
             patch("services.react_agent.streaming.save_qa_placeholder", new_callable=AsyncMock) as mock_save, \
             patch("services.react_agent.streaming.update_qa_answer", new_callable=AsyncMock) as mock_update:
            mock_sys.return_value = "system"
            mock_quota.return_value = (True, None)
            mock_intent.return_value = ("failed_builder_tool", {"module_type": "project"})
            mock_save.return_value = MagicMock(id=42)

            events = []
            async for event in react_loop_stream(
                db=AsyncMock(), user_id=1, resume_id=1, question="修改项目模块",
                tool_mode="builder",
            ):
                events.append(event)

        error_event = next(e for e in events if e["type"] == "tool_error")
        assert error_event["retryable"] is False
        assert "目标模块不存在" in error_event["error"]
        assert not any(e["type"] == "tool_result" for e in events)
        done_event = next(e for e in events if e["type"] == "agent_done")
        assert done_event["degraded"] is True
        persisted_trace = mock_update.call_args.kwargs["db_trace"]
        assert persisted_trace["total_rounds"] == 1
        persisted_round = persisted_trace["rounds"][0]
        assert persisted_round["tool_calls"] == [
            {
                "name": "failed_builder_tool",
                "arguments": '{"module_type": "project", "resume_id": 1}',
                "id": "intent_direct",
            }
        ]
        assert persisted_round["tool_results"] == [
            {
                "name": "failed_builder_tool",
                "result": "⛔ 目标模块不存在",
                "is_error": True,
                "retryable": False,
            }
        ]


# ═══════════════════════════════════════════════════════════════
# 5. process_trace 双载荷
# ═══════════════════════════════════════════════════════════════


class TestProcessTraceDualPayload:
    """SSE 推紧凑摘要，DB 存完整 prompt（Spec 行 459/482）。"""

    @pytest.mark.asyncio
    async def test_done_event_contains_process_trace(self):
        """agent_done 事件包含紧凑 process_trace 摘要（轮数/工具序列/耗时）。"""
        from services.react_agent.streaming import react_loop_stream

        mock_tool_class = _make_mock_tool_class(result="结果")

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
             patch("services.react_agent.loop.manage_l1_context") as mock_l1, \
             patch("services.react_agent.streaming.save_qa_placeholder", new_callable=AsyncMock) as mock_save, \
             patch("services.react_agent.streaming.update_qa_answer", new_callable=AsyncMock) as mock_update:

            mock_sys.return_value = "system"
            mock_quota.return_value = (True, None)
            mock_l1.side_effect = lambda msgs, **kw: msgs
            mock_llm.return_value = _make_response(content="不应到达")
            mock_save.return_value = MagicMock(id=42)
            mock_update.return_value = MagicMock(id=42)

            events = []
            async for event in react_loop_stream(
                db=AsyncMock(), user_id=1, resume_id=1, question="测试",
            ):
                events.append(event)

        done_event = next(e for e in events if e["type"] == "agent_done")
        # process_trace 是紧凑摘要 dict（轮数/工具序列/耗时）
        assert "process_trace" in done_event
        pt = done_event["process_trace"]
        assert isinstance(pt, dict)
        assert "rounds" in pt
        assert "tool_sequence" in pt
        assert "duration_ms" in pt

        # 更新 DB 时传入了 db_trace（完整 prompt）
        mock_update.assert_called_once()
        update_kwargs = mock_update.call_args.kwargs
        assert "db_trace" in update_kwargs
