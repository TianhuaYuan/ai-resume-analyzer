"""SSE 协议字段对齐测试（Spec SSE 事件协议）。

验证 streaming.py 产出的事件符合 Spec：
agent_start    {type, resume_id, tools:[{name,description}...]}
memory_loaded  {type, history_count, profile_loaded}
agent_thought  {type, id, content}
tool_call      {type, id, tool_name, args}
tool_result    {type, id, tool_name, summary, detail, duration_ms}
usage          {type, prompt_tokens, completion_tokens, total, today_total}
done           {type, qa_id, answer, sources, token_usage, process_trace, degraded}
error          {type, message, code}
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.react_agent.loop import ReactLoopResult


def _make_result(answer="答案", trace=None, usage=None, db_trace=None):
    return ReactLoopResult(
        answer=answer,
        process_trace=trace or [],
        usage=usage or {"prompt_tokens": 100, "completion_tokens": 50},
        db_trace=db_trace or {},
    )


def _patch_stream():
    """批量 patch streaming 依赖。"""
    mock_save = AsyncMock()
    mock_save.return_value = MagicMock(id=42)
    mock_update = AsyncMock()
    return {
        "save": patch("services.react_agent.streaming.save_qa_placeholder", new=mock_save),
        "update": patch("services.react_agent.streaming.update_qa_answer", new=mock_update),
    }


# ═══════════════════════════════════════════════════════════════
# 1. agent_start 字段对齐
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_agent_start_has_resume_id_and_tools():
    """agent_start 事件包含 resume_id 和 tools 列表。"""
    from services.react_agent.streaming import react_loop_stream

    async def mock_loop(**kwargs):
        cb = kwargs["event_callback"]
        await cb({"type": "agent_done", "content": "答案"})
        return _make_result()

    with patch("services.react_agent.streaming.react_loop", side_effect=mock_loop), \
         patch("services.react_agent.streaming.save_qa_placeholder", new_callable=AsyncMock) as mock_save, \
         patch("services.react_agent.streaming.update_qa_answer", new_callable=AsyncMock):

        mock_save.return_value = MagicMock(id=42)

        events = []
        async for event in react_loop_stream(db=AsyncMock(), user_id=1, resume_id=7, question="测试"):
            events.append(event)

    starts = [e for e in events if e["type"] == "agent_start"]
    assert len(starts) == 1
    assert starts[0]["resume_id"] == 7
    assert "tools" in starts[0]
    assert isinstance(starts[0]["tools"], list)
    # tools 列表中每个元素应有 name 和 description
    if starts[0]["tools"]:
        assert "name" in starts[0]["tools"][0]
        assert "description" in starts[0]["tools"][0]


# ═══════════════════════════════════════════════════════════════
# 2. memory_loaded 事件转发
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_memory_loaded_event_forwarded():
    """memory_loaded 事件被转发到 SSE 流。"""
    from services.react_agent.streaming import react_loop_stream

    async def mock_loop(**kwargs):
        cb = kwargs["event_callback"]
        await cb({"type": "memory_loaded", "history_count": 5, "profile_loaded": True})
        await cb({"type": "agent_done", "content": "答案"})
        return _make_result()

    with patch("services.react_agent.streaming.react_loop", side_effect=mock_loop), \
         patch("services.react_agent.streaming.save_qa_placeholder", new_callable=AsyncMock) as mock_save, \
         patch("services.react_agent.streaming.update_qa_answer", new_callable=AsyncMock):

        mock_save.return_value = MagicMock(id=42)

        events = []
        async for event in react_loop_stream(db=AsyncMock(), user_id=1, resume_id=1, question="测试"):
            events.append(event)

    mem_events = [e for e in events if e["type"] == "memory_loaded"]
    assert len(mem_events) == 1
    assert mem_events[0]["history_count"] == 5
    assert mem_events[0]["profile_loaded"] is True


# ═══════════════════════════════════════════════════════════════
# 3. tool_call 字段对齐
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_tool_call_fields_renamed():
    """tool_call 事件字段对齐 Spec：tool_name, args（非 name, arguments）。"""
    from services.react_agent.streaming import react_loop_stream

    async def mock_loop(**kwargs):
        cb = kwargs["event_callback"]
        await cb({
            "type": "tool_call",
            "name": "search_resume",
            "arguments": '{"resume_id": 1, "query": "test"}',
            "id": "tc_1",
        })
        await cb({"type": "agent_done", "content": "答案"})
        return _make_result()

    with patch("services.react_agent.streaming.react_loop", side_effect=mock_loop), \
         patch("services.react_agent.streaming.save_qa_placeholder", new_callable=AsyncMock) as mock_save, \
         patch("services.react_agent.streaming.update_qa_answer", new_callable=AsyncMock):

        mock_save.return_value = MagicMock(id=42)

        events = []
        async for event in react_loop_stream(db=AsyncMock(), user_id=1, resume_id=1, question="测试"):
            events.append(event)

    tool_calls = [e for e in events if e["type"] == "tool_call"]
    assert len(tool_calls) == 1
    assert "tool_name" in tool_calls[0]
    assert "args" in tool_calls[0]
    assert tool_calls[0]["tool_name"] == "search_resume"


# ═══════════════════════════════════════════════════════════════
# 4. tool_result 字段对齐
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_tool_result_fields_renamed():
    """tool_result 事件字段对齐 Spec：tool_name, summary, detail。"""
    from services.react_agent.streaming import react_loop_stream

    async def mock_loop(**kwargs):
        cb = kwargs["event_callback"]
        await cb({"type": "tool_call", "name": "search_resume", "arguments": "{}", "id": "tc_1"})
        await cb({"type": "tool_result", "name": "search_resume", "result": "完整结果", "id": "tc_1"})
        await cb({"type": "agent_done", "content": "答案"})
        return _make_result()

    with patch("services.react_agent.streaming.react_loop", side_effect=mock_loop), \
         patch("services.react_agent.streaming.save_qa_placeholder", new_callable=AsyncMock) as mock_save, \
         patch("services.react_agent.streaming.update_qa_answer", new_callable=AsyncMock):

        mock_save.return_value = MagicMock(id=42)

        events = []
        async for event in react_loop_stream(db=AsyncMock(), user_id=1, resume_id=1, question="测试"):
            events.append(event)

    tool_results = [e for e in events if e["type"] == "tool_result"]
    assert len(tool_results) == 1
    assert "tool_name" in tool_results[0]
    assert "summary" in tool_results[0]
    assert "detail" in tool_results[0]


# ═══════════════════════════════════════════════════════════════
# 5. usage 事件扁平化
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_usage_event_flattened():
    """usage 事件扁平化：prompt_tokens, completion_tokens, total（非嵌套）。"""
    from services.react_agent.streaming import react_loop_stream

    async def mock_loop(**kwargs):
        cb = kwargs["event_callback"]
        await cb({
            "type": "usage",
            "usage": {"prompt_tokens": 200, "completion_tokens": 80},
            "total": {"prompt_tokens": 200, "completion_tokens": 80},
        })
        await cb({"type": "agent_done", "content": "答案"})
        return _make_result()

    with patch("services.react_agent.streaming.react_loop", side_effect=mock_loop), \
         patch("services.react_agent.streaming.save_qa_placeholder", new_callable=AsyncMock) as mock_save, \
         patch("services.react_agent.streaming.update_qa_answer", new_callable=AsyncMock):

        mock_save.return_value = MagicMock(id=42)

        events = []
        async for event in react_loop_stream(db=AsyncMock(), user_id=1, resume_id=1, question="测试"):
            events.append(event)

    usage_events = [e for e in events if e["type"] == "usage"]
    assert len(usage_events) == 1
    assert usage_events[0]["prompt_tokens"] == 200
    assert usage_events[0]["completion_tokens"] == 80
    assert "total" in usage_events[0]


# ═══════════════════════════════════════════════════════════════
# 6. agent_done 字段对齐
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_agent_done_has_degraded_and_token_usage():
    """agent_done 事件包含 degraded 和 token_usage 字段。"""
    from services.react_agent.streaming import react_loop_stream

    async def mock_loop(**kwargs):
        cb = kwargs["event_callback"]
        await cb({"type": "agent_done", "content": "答案"})
        return _make_result(usage={"prompt_tokens": 200, "completion_tokens": 80})

    with patch("services.react_agent.streaming.react_loop", side_effect=mock_loop), \
         patch("services.react_agent.streaming.save_qa_placeholder", new_callable=AsyncMock) as mock_save, \
         patch("services.react_agent.streaming.update_qa_answer", new_callable=AsyncMock):

        mock_save.return_value = MagicMock(id=42)

        events = []
        async for event in react_loop_stream(db=AsyncMock(), user_id=1, resume_id=1, question="测试"):
            events.append(event)

    dones = [e for e in events if e["type"] == "agent_done"]
    assert len(dones) == 1
    assert "degraded" in dones[0]
    assert "token_usage" in dones[0]
    assert dones[0]["token_usage"]["prompt_tokens"] == 200
    assert dones[0]["degraded"] is False


@pytest.mark.asyncio
async def test_agent_usage_has_one_quota_owner_and_shared_final_total():
    """最终聚合 usage 同时驱动 QAHistory、quota 与 agent_done，quota 只写一次。"""
    from services.react_agent.streaming import react_loop_stream

    usage = {"prompt_tokens": 200, "completion_tokens": 80}

    async def mock_loop(**kwargs):
        await kwargs["event_callback"]({"type": "agent_done", "content": "答案"})
        return _make_result(usage=usage)

    with patch("services.react_agent.streaming.react_loop", side_effect=mock_loop), \
         patch("services.react_agent.streaming.save_qa_placeholder", new_callable=AsyncMock) as mock_save, \
         patch("services.react_agent.streaming.update_qa_answer", new_callable=AsyncMock) as mock_update, \
         patch("services.token_quota.record_usage", new_callable=AsyncMock) as mock_quota:
        mock_save.return_value = MagicMock(id=42)
        events = [
            event
            async for event in react_loop_stream(
                db=AsyncMock(), user_id=7, resume_id=1, question="测试"
            )
        ]

    mock_quota.assert_awaited_once_with(7, 200, 80)
    assert mock_update.await_args.kwargs["token_usage"] == usage
    done = next(event for event in events if event["type"] == "agent_done")
    assert done["token_usage"] == usage


@pytest.mark.asyncio
async def test_agent_missing_provider_usage_does_not_record_quota():
    """provider 未返回 token 时保留零 usage，不虚构、不写 quota。"""
    from services.react_agent.streaming import react_loop_stream

    usage = {"prompt_tokens": 0, "completion_tokens": 0}

    async def mock_loop(**kwargs):
        await kwargs["event_callback"]({"type": "agent_done", "content": "降级答案"})
        return _make_result(answer="降级答案", usage=usage)

    with patch("services.react_agent.streaming.react_loop", side_effect=mock_loop), \
         patch("services.react_agent.streaming.save_qa_placeholder", new_callable=AsyncMock) as mock_save, \
         patch("services.react_agent.streaming.update_qa_answer", new_callable=AsyncMock) as mock_update, \
         patch("services.token_quota.record_usage", new_callable=AsyncMock) as mock_quota:
        mock_save.return_value = MagicMock(id=42)
        events = [
            event
            async for event in react_loop_stream(
                db=AsyncMock(), user_id=7, resume_id=1, question="测试"
            )
        ]

    mock_quota.assert_not_awaited()
    assert mock_update.await_args.kwargs["token_usage"] == usage
    done = next(event for event in events if event["type"] == "agent_done")
    assert done["token_usage"] == usage


@pytest.mark.asyncio
async def test_agent_done_degraded_when_tool_error():
    """agent_done 的 degraded=True 当 process_trace 含 tool_error。"""
    from services.react_agent.streaming import react_loop_stream

    trace_with_error = [
        {"type": "tool_call", "name": "bad_tool", "arguments": "{}", "id": "tc_1"},
        {"type": "tool_error", "name": "bad_tool", "error": "失败", "id": "tc_1"},
        {"type": "agent_done", "content": "降级答案"},
    ]

    async def mock_loop(**kwargs):
        cb = kwargs["event_callback"]
        for e in trace_with_error:
            await cb(e)
        return _make_result(answer="降级答案", trace=trace_with_error)

    with patch("services.react_agent.streaming.react_loop", side_effect=mock_loop), \
         patch("services.react_agent.streaming.save_qa_placeholder", new_callable=AsyncMock) as mock_save, \
         patch("services.react_agent.streaming.update_qa_answer", new_callable=AsyncMock):

        mock_save.return_value = MagicMock(id=42)

        events = []
        async for event in react_loop_stream(db=AsyncMock(), user_id=1, resume_id=1, question="测试"):
            events.append(event)

    dones = [e for e in events if e["type"] == "agent_done"]
    assert len(dones) == 1
    assert dones[0]["degraded"] is True


@pytest.mark.asyncio
async def test_agent_done_has_sources_field():
    """agent_done 事件包含 sources 字段（即使为空）。"""
    from services.react_agent.streaming import react_loop_stream

    async def mock_loop(**kwargs):
        cb = kwargs["event_callback"]
        await cb({"type": "agent_done", "content": "答案"})
        return _make_result()

    with patch("services.react_agent.streaming.react_loop", side_effect=mock_loop), \
         patch("services.react_agent.streaming.save_qa_placeholder", new_callable=AsyncMock) as mock_save, \
         patch("services.react_agent.streaming.update_qa_answer", new_callable=AsyncMock):

        mock_save.return_value = MagicMock(id=42)

        events = []
        async for event in react_loop_stream(db=AsyncMock(), user_id=1, resume_id=1, question="测试"):
            events.append(event)

    dones = [e for e in events if e["type"] == "agent_done"]
    assert len(dones) == 1
    assert "sources" in dones[0]


# ═══════════════════════════════════════════════════════════════
# 7. DB 持久化完整 prompt（Spec: 完整 prompt 进 DB，紧凑摘要进 SSE）
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_update_qa_answer_saves_db_trace_to_db():
    """update_qa_answer 将 db_trace 保存到 DB process_trace 列。"""
    from services.react_agent.streaming import update_qa_answer

    mock_record = MagicMock()
    mock_record.id = 1
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_record
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)

    db_trace = {
        "system_prompt": "你是简历助手...",
        "rounds": [{"round": 1, "model": "judge"}],
        "total_rounds": 1,
    }

    await update_qa_answer(
        db=mock_db,
        qa_id=1,
        answer="答案",
        sources=[],
        token_usage={"prompt_tokens": 100, "completion_tokens": 50},
        db_trace=db_trace,
    )

    assert mock_record.process_trace == db_trace
    assert mock_record.status == "complete"
    assert mock_record.token_usage == 150


@pytest.mark.asyncio
async def test_stream_passes_db_trace_to_update():
    """react_loop_stream 将 loop_result.db_trace 传给 update_qa_answer。"""
    from services.react_agent.streaming import react_loop_stream

    db_trace = {
        "system_prompt": "你是简历助手...",
        "rounds": [{"round": 1, "model": "judge"}],
        "total_rounds": 1,
    }

    async def mock_loop(**kwargs):
        cb = kwargs["event_callback"]
        await cb({"type": "agent_done", "content": "答案"})
        return _make_result(db_trace=db_trace)

    with patch("services.react_agent.streaming.react_loop", side_effect=mock_loop), \
         patch("services.react_agent.streaming.save_qa_placeholder", new_callable=AsyncMock) as mock_save, \
         patch("services.react_agent.streaming.update_qa_answer", new_callable=AsyncMock) as mock_update:

        mock_save.return_value = MagicMock(id=42)

        events = []
        async for event in react_loop_stream(db=AsyncMock(), user_id=1, resume_id=1, question="测试"):
            events.append(event)

    call_kwargs = mock_update.call_args.kwargs
    assert call_kwargs.get("db_trace") == db_trace


@pytest.mark.asyncio
async def test_stream_done_has_compact_trace():
    """SSE done 的 process_trace 是紧凑摘要（rounds/tool_sequence/duration_ms），不是全量事件列表。"""
    from services.react_agent.streaming import react_loop_stream

    full_trace = [
        {"type": "tool_call", "name": "search_resume", "arguments": "{}", "id": "tc_1"},
        {"type": "tool_result", "name": "search_resume", "result": "结果", "id": "tc_1"},
        {"type": "agent_done", "content": "答案"},
    ]

    async def mock_loop(**kwargs):
        cb = kwargs["event_callback"]
        for e in full_trace:
            await cb(e)
        return _make_result(trace=full_trace)

    with patch("services.react_agent.streaming.react_loop", side_effect=mock_loop), \
         patch("services.react_agent.streaming.save_qa_placeholder", new_callable=AsyncMock) as mock_save, \
         patch("services.react_agent.streaming.update_qa_answer", new_callable=AsyncMock):

        mock_save.return_value = MagicMock(id=42)

        events = []
        async for event in react_loop_stream(db=AsyncMock(), user_id=1, resume_id=1, question="测试"):
            events.append(event)

    dones = [e for e in events if e["type"] == "agent_done"]
    assert len(dones) == 1
    pt = dones[0]["process_trace"]
    # 紧凑摘要应包含 rounds, tool_sequence, duration_ms
    assert "rounds" in pt
    assert "tool_sequence" in pt
    assert pt["rounds"] == 1
    assert pt["tool_sequence"] == ["search_resume"]
