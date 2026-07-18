"""
阶段2 / H6·M6（rerank 复用 Cross-Encoder）测试。

验证 mcp_server/tools/rerank.py 改为复用 services.rag_service.rerank
（已有的 Cross-Encoder 精排），而不是用 LLM 重新打分：
- 调用入口是 services.rag_service.rerank
- 旧的 llm_generate 打分路径不再被使用
- 输出格式与 Cross-Encoder 结果一致
"""
import json

import pytest
from unittest.mock import AsyncMock, patch

from mcp_server.server import _current_user_id


@pytest.mark.asyncio
async def test_rerank_reuses_rag_service_rerank():
    from mcp_server.tools.rerank import rerank_results

    token = _current_user_id.set(7)
    try:
        fake = [
            {"text": "A", "rerank_score": 0.9, "section": "经历", "chunk_index": 0},
            {"text": "B", "rerank_score": 0.6, "section": "技能", "chunk_index": 1},
        ]
        with (
            patch("services.rag.retrieval.rerank", new_callable=AsyncMock, return_value=fake),
            patch("services.rag.pipeline.llm_generate", new_callable=AsyncMock) as mock_llm,
        ):
            result = await rerank_results(
                "查询", '[{"text":"A"},{"text":"B"}]', top_k=2,
            )
        # 关键：必须调用已有的 Cross-Encoder rerank，而非 LLM 打分
        # （mock_llm 未被 await 说明旧路径已移除）
        mock_llm.assert_not_awaited()
        data = json.loads(result[0].text)
        assert isinstance(data, list)
        assert len(data) == 2
        assert data[0]["text"] == "A"
        # rerank_score 透传
        assert data[0]["rerank_score"] == 0.9
    finally:
        _current_user_id.reset(token)


@pytest.mark.asyncio
async def test_rerank_passes_query_chunks_topk():
    from mcp_server.tools.rerank import rerank_results

    token = _current_user_id.set(7)
    try:
        captured = {}

        async def _fake_rerank(query, chunks, top_k=5):
            captured["query"] = query
            captured["chunks"] = chunks
            captured["top_k"] = top_k
            return [{"text": c.get("text", ""), "rerank_score": 1.0,
                    "section": c.get("section", ""), "chunk_index": i}
                   for i, c in enumerate(chunks)][:top_k]

        with patch("services.rag.retrieval.rerank", side_effect=_fake_rerank):
            await rerank_results("我的技能", '[{"text":"X","section":"s","chunk_index":0}]', top_k=3)

        assert captured["query"] == "我的技能"
        assert captured["top_k"] == 3
        assert captured["chunks"] == [{"text": "X", "section": "s", "chunk_index": 0}]
    finally:
        _current_user_id.reset(token)


@pytest.mark.asyncio
async def test_rerank_empty_chunks_returns_empty():
    from mcp_server.tools.rerank import rerank_results

    token = _current_user_id.set(7)
    try:
        with patch("services.rag.retrieval.rerank", new_callable=AsyncMock) as m:
            result = await rerank_results("查询", "[]")
        # 空列表不应触发 rerank 调用
        m.assert_not_awaited()
        data = json.loads(result[0].text)
        assert data.get("results") == []
    finally:
        _current_user_id.reset(token)
