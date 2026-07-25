"""P1-22: mcp_search_node 空结果时应记录 tool_errors。

原 bug：MCP 搜索返回空时，mcp_search_node 只返回空 chunks，
不记录 tool_errors，导致下游 generate 节点无法感知检索失败、
API 层 degraded 标记永远为 False。
"""
from unittest.mock import AsyncMock, patch

import pytest

from services.agentic_rag.mcp_nodes import mcp_search_node


@pytest.mark.asyncio
async def test_mcp_search_empty_results_records_tool_error():
    """MCP 搜索返回空列表时，应在 tool_errors 中记录失败。"""
    state = {
        "question": "测试问题",
        "rewritten_query": "改写后的问题",
        "resume_id": 1,
        "search_round": 0,
        "trace": {},
        "tool_errors": [],
    }

    with patch(
        "services.agentic_rag.mcp_nodes.mcp_search",
        new_callable=AsyncMock,
        return_value=[],  # 空结果
    ):
        result = await mcp_search_node(state)

    assert result["chunks"] == []
    tool_errors = result.get("tool_errors", [])
    assert len(tool_errors) == 1, f"空结果应记录 1 条 tool_error，实际 {len(tool_errors)}"
    err = tool_errors[0]
    assert err["tool"] == "mcp_search"
    assert "query" in err
    assert "error" in err
    assert err["query"] == "改写后的问题"


@pytest.mark.asyncio
async def test_mcp_search_non_empty_results_no_tool_error():
    """MCP 搜索有结果时，不应添加 tool_error。"""
    state = {
        "question": "测试问题",
        "rewritten_query": "改写后的问题",
        "resume_id": 1,
        "search_round": 0,
        "trace": {},
        "tool_errors": [],
    }

    mock_chunks = [{"text": "有效段落", "chunk_index": 0, "section": "edu"}]
    with patch(
        "services.agentic_rag.mcp_nodes.mcp_search",
        new_callable=AsyncMock,
        return_value=mock_chunks,
    ):
        result = await mcp_search_node(state)

    assert len(result["chunks"]) == 1
    assert result.get("tool_errors", []) == [], "有结果时不应添加 tool_error"


@pytest.mark.asyncio
async def test_mcp_search_preserves_existing_tool_errors():
    """已有 tool_errors 时应累加，不覆盖。"""
    existing_error = {"tool": "previous_step", "query": "old", "error": "old error"}
    state = {
        "question": "测试问题",
        "rewritten_query": "改写后的问题",
        "resume_id": 1,
        "search_round": 1,
        "trace": {},
        "tool_errors": [existing_error],
    }

    with patch(
        "services.agentic_rag.mcp_nodes.mcp_search",
        new_callable=AsyncMock,
        return_value=[],  # 空结果
    ):
        result = await mcp_search_node(state)

    tool_errors = result["tool_errors"]
    assert len(tool_errors) == 2, "应累加到 2 条（1 已有 + 1 新增）"
    assert existing_error in tool_errors, "已有的 tool_error 应保留"
