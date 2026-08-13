"""
MCP Search 字段名测试：验证 search_knowledge_base 返回结果包含 'text' 字段。

字段契约：search_knowledge_base 统一返回 'text' 字段。历史版本曾用 'content'，
导致 MCP 客户端读取不到内容，后将 'content' 统一为 'text'。
"""

import pytest


class TestMCPSearchFieldName:
    """MCP Search 工具返回字段名验证。"""

    @pytest.mark.asyncio
    async def test_search_knowledge_base_returns_text_field(self):
        """search_knowledge_base 返回结果必须包含 'text' 字段而非 'content'。"""
        from mcp_server.tools.search import search_knowledge_base

        from mcp_server.server import _current_user_id

        token = _current_user_id.set(1)

        from unittest.mock import patch, AsyncMock

        mock_chunks = [
            {
                "text": "测试简历内容",
                "chunk_index": 0,
                "section": "工作经历",
                "score": 0.9,
            }
        ]

        try:
            with (
                patch(
                    "mcp_server.tools.search.assert_user_owns_assets",
                    new_callable=AsyncMock,
                    return_value={"resume": [1]},
                ),
                patch(
                    "services.rag.retrieval.hybrid_search_corpus",
                    new_callable=AsyncMock,
                    return_value=mock_chunks,
                ),
            ):
                result = await search_knowledge_base(
                    query="测试查询",
                    resume_id="1",
                    top_k=1,
                )

            assert len(result) == 1
            import json

            data = json.loads(result[0].text)
            assert isinstance(data, list)
            assert len(data) == 1

            item = data[0]
            assert "text" in item, f"Expected 'text' field but got keys: {list(item.keys())}"
            assert item["text"] == "测试简历内容"
        finally:
            _current_user_id.reset(token)

    @pytest.mark.asyncio
    async def test_mcp_search_uses_text_field(self):
        """mcp_search 正确读取 'text' 字段用于生成上下文。"""

        mock_chunks = [
            {
                "text": "在某公司担任Python开发工程师",
                "chunk_index": 0,
                "section": "工作经历",
                "rerank_score": 0.9,
            }
        ]

        context = "\n\n".join(f"[段落 {i + 1}] {c.get('text', '')}" for i, c in enumerate(mock_chunks))

        assert "Python开发工程师" in context
        assert "[段落 1]" in context