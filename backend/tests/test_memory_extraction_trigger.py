"""记忆提炼触发器（A2/A3）：节流 + react_loop_stream 接线。"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.config import settings


class TestThrottleTrigger:
    @pytest.mark.asyncio
    async def test_disabled_returns_false(self):
        """开关关闭 → 直接 False，不触碰 Redis/提取。"""
        from services.memory.extraction_trigger import maybe_extract_memories

        with patch.object(settings, "MEMORY_EXTRACTION_ENABLED", False), patch(
            "services.memory.extraction_trigger._throttle_acquire",
            new_callable=AsyncMock,
        ) as mock_throttle:
            result = await maybe_extract_memories(user_id=1, conversation_text="你好")

        assert result is False
        mock_throttle.assert_not_called()

    @pytest.mark.asyncio
    async def test_throttle_blocks(self):
        """Redis SET NX 返回 None（节流窗口内）→ 不提炼。"""
        from services.memory.extraction_trigger import maybe_extract_memories

        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock(return_value=None)  # 未获取到锁
        with patch.object(settings, "MEMORY_EXTRACTION_ENABLED", True), patch(
            "core.redis_client.get_redis",
            new_callable=AsyncMock,
            return_value=mock_redis,
        ), patch(
            "services.memory.extraction.extract_and_save_memories",
            new_callable=AsyncMock,
        ) as mock_extract:
            result = await maybe_extract_memories(user_id=1, conversation_text="你好")

        assert result is False
        mock_extract.assert_not_called()
        mock_redis.set.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_throttle_allows_extraction(self):
        """Redis SET NX 返回 True → 调用提取。"""
        from services.memory.extraction_trigger import maybe_extract_memories

        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock(return_value=True)
        with patch.object(settings, "MEMORY_EXTRACTION_ENABLED", True), patch(
            "core.redis_client.get_redis",
            new_callable=AsyncMock,
            return_value=mock_redis,
        ), patch(
            "services.memory.extraction.extract_and_save_memories",
            new_callable=AsyncMock,
        ) as mock_extract:
            result = await maybe_extract_memories(user_id=1, conversation_text="你好")

        assert result is True
        mock_extract.assert_awaited_once()
        mock_extract.await_args.kwargs["user_id"] == 1

    @pytest.mark.asyncio
    async def test_inproc_fallback_when_redis_down(self):
        """Redis 异常 → 回退 in-process dict 节流。"""
        from services.memory.extraction_trigger import maybe_extract_memories, _extract_lock

        _extract_lock.clear()
        with patch.object(settings, "MEMORY_EXTRACTION_ENABLED", True), patch(
            "core.redis_client.get_redis",
            new_callable=AsyncMock,
            side_effect=Exception("redis down"),
        ), patch(
            "services.memory.extraction.extract_and_save_memories",
            new_callable=AsyncMock,
        ) as mock_extract:
            r1 = await maybe_extract_memories(user_id=42, conversation_text="A")
            r2 = await maybe_extract_memories(user_id=42, conversation_text="B")

        assert r1 is True
        assert r2 is False  # 节流窗口内第二次被拦
        assert mock_extract.await_count == 1

    @pytest.mark.asyncio
    async def test_extract_error_does_not_raise(self):
        """提取内部异常 → 记录日志返回 False，不冒泡。"""
        from services.memory.extraction_trigger import maybe_extract_memories

        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock(return_value=True)
        with patch.object(settings, "MEMORY_EXTRACTION_ENABLED", True), patch(
            "core.redis_client.get_redis",
            new_callable=AsyncMock,
            return_value=mock_redis,
        ), patch(
            "services.memory.extraction.extract_and_save_memories",
            new_callable=AsyncMock,
            side_effect=Exception("boom"),
        ):
            result = await maybe_extract_memories(user_id=1, conversation_text="你好")

        assert result is False


# ── react_loop_stream 接线 ────────────────────────────────────


def _make_react_loop_result() -> MagicMock:
    from services.react_agent.loop import ReactLoopResult

    return ReactLoopResult(
        answer="这是一个测试回答",
        usage={"prompt_tokens": 10, "completion_tokens": 5},
    )


async def _run_stream(tool_mode: str = "agent"):
    """驱动 react_loop_stream 收集所有事件。"""
    from services.react_agent.streaming import react_loop_stream

    async def _fake_react_loop(**kwargs):
        event_callback = kwargs.get("event_callback")
        if event_callback:
            await event_callback({"type": "agent_done", "content": "已生成"})
        return _make_react_loop_result()

    with patch(
        "services.react_agent.streaming.react_loop",
        side_effect=_fake_react_loop,
    ), patch(
        "services.react_agent.streaming.save_qa_placeholder",
        new_callable=AsyncMock,
        return_value=MagicMock(id=1),
    ), patch(
        "services.react_agent.streaming.update_qa_answer",
        new_callable=AsyncMock,
    ), patch(
        "services.react_agent.streaming._build_compact_trace",
        return_value={},
    ), patch(
        "services.react_agent.streaming._has_tool_error",
        return_value=False,
    ), patch(
        "services.token_quota.record_usage",
        new_callable=AsyncMock,
    ):
        events = [e async for e in react_loop_stream(
            db=MagicMock(), user_id=1, resume_id=1,
            question="你叫什么", tool_mode=tool_mode,
        )]
    return events


@pytest.mark.asyncio
async def test_react_loop_stream_schedules_extraction():
    """开关开启 + agent 模式 → maybe_extract_memories 被调度。"""

    with patch.object(settings, "MEMORY_EXTRACTION_ENABLED", True), patch(
        "services.memory.extraction_trigger.maybe_extract_memories",
        new_callable=AsyncMock,
    ) as mock_extract:
        # _run_stream 内部真实调度 create_task(maybe_extract_memories(...))
        events = await _run_stream(tool_mode="agent")
        await asyncio.sleep(0.05)  # 让 fire-and-forget task 运行

    assert any(e["type"] == "agent_done" for e in events)
    assert mock_extract.await_count >= 1


@pytest.mark.asyncio
async def test_react_loop_stream_skips_builder():
    """builder 模式 → 不调度提炼（编辑器操作不是用户个人事实）。"""

    with patch.object(settings, "MEMORY_EXTRACTION_ENABLED", True), patch(
        "services.memory.extraction_trigger.maybe_extract_memories",
        new_callable=AsyncMock,
    ) as mock_extract:
        events = await _run_stream(tool_mode="builder")
        await asyncio.sleep(0.05)

    assert any(e["type"] == "agent_done" for e in events)
    assert mock_extract.await_count == 0
