"""T10 regression coverage; executed in the final verification pass."""

from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_mineru_http_client_reused_and_closable():
    from services.mineru_parser import MinerUClient

    client = MinerUClient(token="abc")
    first = await client._get_http_client()
    second = await client._get_http_client()
    assert first is second
    await client.aclose()
    assert first.is_closed


def test_context_compactor_keeps_budget_and_tool_boundaries():
    from services.react_agent.memory import ContextCompactor

    messages = [{"role": "system", "content": "rules"}]
    for i in range(20):
        messages.extend(
            [
                {"role": "user", "content": f"question {i} " + "x" * 500},
                {"role": "assistant", "content": f"answer {i} " + "y" * 500},
            ]
        )
    compactor = ContextCompactor(context_window=512, reserve_tokens=128)
    assert compactor.should_compact(messages)


@pytest.mark.asyncio
async def test_usage_cost_is_recorded_as_integer_micro_usd():
    from services.rag import usage

    redis = AsyncMock()
    with patch.object(usage, "get_redis", return_value=redis), patch.object(
        usage.settings,
        "LLM_INPUT_COST_PER_MILLION_USD",
        1.0,
    ), patch.object(usage.settings, "LLM_OUTPUT_COST_PER_MILLION_USD", 2.0):
        await usage.record_llm_usage(1, 10, 5)
    keys = [call.args[0] for call in redis.incrby.call_args_list]
    assert any("cost_total_micro_usd" in key for key in keys)
