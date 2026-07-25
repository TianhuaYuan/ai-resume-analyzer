"""
简单测试：验证 search_knowledge_base 返回 'text' 字段。

独立测试脚本，不依赖 conftest.py 的复杂依赖。
"""

import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_search_returns_text_field():
    """search_knowledge_base 返回结果必须包含 'text' 字段。"""
    from unittest.mock import patch, MagicMock

    mock_chunks = [
        {"text": "测试简历内容", "chunk_index": 0, "section": "工作经历", "score": 0.9}
    ]

    with (
        patch("mcp_server.tools.search.AsyncSessionLocal", return_value=MagicMock()),
        patch("mcp_server.tools.search.hybrid_search", return_value=mock_chunks),
        patch("mcp_server.tools.search.rerank", return_value=mock_chunks),
    ):
        from mcp_server.tools.search import search_knowledge_base
        from mcp_server.server import _current_user_id
        _current_user_id.set(1)
        import asyncio
        result = asyncio.run(search_knowledge_base(query="测试", resume_id="1", top_k=1))

    assert len(result) == 1
    data = json.loads(result[0].text)
    assert isinstance(data, list)
    assert len(data) == 1

    item = data[0]
    assert "text" in item, f"Expected 'text' field but got keys: {list(item.keys())}"
    assert item["text"] == "测试简历内容"


if __name__ == "__main__":
    test_search_returns_text_field()
    print("TEST PASSED")