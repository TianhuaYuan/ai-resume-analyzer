"""临时验证脚本：确认 react_loop_stream 走完整流程（含 L354 注入队列清理）不抛 NameError。"""
import asyncio
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from services.react_agent import streaming


class _Result:
    answer = "test answer"
    sources = [{"text": "s", "score": 0.9}]
    usage = {"prompt_tokens": 10, "completion_tokens": 5}
    db_trace = [{"type": "tool_call", "name": "search_resume"}]
    process_trace = [{"type": "tool_call", "name": "search_resume"}]


async def fake_react_loop(**kw):
    await kw["event_callback"]({"type": "agent_done", "content": "test answer", "usage": {}})
    return _Result()


async def main():
    with (
        patch.object(streaming, "react_loop", side_effect=fake_react_loop),
        patch.object(streaming, "save_qa_placeholder", new=AsyncMock(return_value=SimpleNamespace(id=1))),
        patch.object(streaming, "update_qa_answer", new=AsyncMock()),
        patch("core.redis_client.get_redis", new=AsyncMock(return_value=None)),
    ):
        events = []
        async for ev in streaming.react_loop_stream(
            db=None, user_id=1, resume_id=1, question="hi", tool_mode="agent"
        ):
            events.append(ev)
        types = [e["type"] for e in events]
        print("event types:", types)
        assert "agent_done" in types, f"缺少 agent_done: {types}"
        assert all(t != "error" for t in types), f"出现 error 事件: {types}"
        print("PASS: 完整流程跑通，L354 注入队列清理不再抛 NameError")


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
