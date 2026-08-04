"""P2-3b: mcp_client.tools.mcp_rerank 降级路径不得原地修改输入 chunks。

mcp_client/tools.py 的 rerank 降级路径曾用 c.setdefault 原地修改
传入的 chunks 列表，污染调用方数据。本测试守护该不可变性。
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mcp_client.client import MCPClientError
from mcp_client.tools import mcp_rerank


@pytest.mark.asyncio
async def test_mcp_rerank_fallback_does_not_mutate_input():
    """MCP 返回 MCPClientError 走降级路径，输入 chunks 不应被原地修改。"""
    original = [
        {"text": "段落A", "chunk_index": 0},
        {"text": "段落B", "chunk_index": 1},
    ]

    mock_client = MagicMock()
    mock_client.connect = AsyncMock()
    mock_client.call_tool = AsyncMock(side_effect=MCPClientError("rerank failed"))

    with patch("mcp_client.tools.get_mcp_client", return_value=mock_client):
        result = await mcp_rerank("query", original, top_k=5)

    for orig in original:
        assert "rerank_score" not in orig, "原始 chunks 不应被原地修改"

    assert len(result) == 2
    for c in result:
        assert c["rerank_score"] == 0.5
