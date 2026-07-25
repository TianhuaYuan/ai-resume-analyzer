"""P2-3: mcp_rerank_node 降级路径不得原地修改 state 中的 chunks。

原 bug：rerank 降级时 `for c in chunks: c.setdefault("rerank_score", 0.5)`
会直接往 state 的 chunks dict 里塞 key，污染后续轮次的 state。
"""
from unittest.mock import AsyncMock, patch

import pytest

from services.agentic_rag.mcp_nodes import mcp_rerank_node


@pytest.mark.asyncio
async def test_mcp_rerank_fallback_does_not_mutate_input_chunks():
    """rerank 返回空时走降级路径，原始 chunks 不应被原地修改。"""
    original_chunks = [
        {"text": "段落A", "chunk_index": 0, "section": "edu"},
        {"text": "段落B", "chunk_index": 1, "section": "exp"},
    ]
    # 深拷贝一份，用于事后比对
    snapshot = [{**c} for c in original_chunks]

    state = {
        "question": "测试问题",
        "rewritten_query": "测试问题",
        "chunks": original_chunks,
        "trace": {},
    }

    with patch(
        "services.agentic_rag.mcp_nodes.mcp_rerank",
        new_callable=AsyncMock,
        return_value=[],  # 触发降级路径
    ):
        result = await mcp_rerank_node(state)

    # 原始 chunks 的每个 dict 不应被添加 rerank_score
    for original, snap in zip(original_chunks, snapshot):
        assert "rerank_score" not in snap, "snapshot 不应被改动（它是深拷贝）"
        assert "rerank_score" not in original, (
            f"原始 chunks 不应被原地修改，但发现 rerank_score={original.get('rerank_score')}"
        )

    # 返回的 reranked 应该是新对象，且带 rerank_score
    reranked = result["chunks"]
    assert len(reranked) == 2
    for c in reranked:
        assert "rerank_score" in c, "降级路径应给每个 chunk 补 rerank_score=0.5"
        assert c["rerank_score"] == 0.5
