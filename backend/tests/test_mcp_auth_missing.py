"""
阶段2 / SEC-002（Critical 三工具补认证）测试。

验证 generate.py / rewrite.py / rerank.py 三个 MCP 工具入口
补充了用户身份校验（get_current_user_id）：
- 缺失用户上下文（contextvar 未设置）→ 按现有错误格式拒绝，不静默放行
- 存在用户上下文 → 正常调用底层服务
"""
import json

import pytest
from unittest.mock import AsyncMock, patch

from mcp_server.server import _current_user_id


# ── 无用户上下文：应拒绝 ─────────────────────────────────

def _ensure_no_user_context():
    """显式清空 contextvar，确保构造出『缺失用户上下文』场景。"""
    try:
        token = _current_user_id.set(1)
        _current_user_id.reset(token)
    except Exception:
        pass
    try:
        _current_user_id.get()
        return False  # 仍然可读，无法构造缺失场景
    except LookupError:
        return True


@pytest.mark.asyncio
async def test_generate_rejects_without_user_context():
    from mcp_server.tools.generate import generate_answer

    if not _ensure_no_user_context():
        pytest.skip("contextvar 仍存在，无法构造缺失场景")

    result = await generate_answer("问题", "一些上下文", "1")
    data = json.loads(result[0].text)
    assert "error" in data
    assert "authentication" in data["error"].lower()


@pytest.mark.asyncio
async def test_rewrite_rejects_without_user_context():
    from mcp_server.tools.rewrite import rewrite_query

    if not _ensure_no_user_context():
        pytest.skip("contextvar 仍存在，无法构造缺失场景")

    result = await rewrite_query("问题")
    data = json.loads(result[0].text)
    assert "error" in data
    assert "authentication" in data["error"].lower()


@pytest.mark.asyncio
async def test_rerank_rejects_without_user_context():
    from mcp_server.tools.rerank import rerank_results

    if not _ensure_no_user_context():
        pytest.skip("contextvar 仍存在，无法构造缺失场景")

    result = await rerank_results("查询", '[{"text": "片段"}]')
    data = json.loads(result[0].text)
    assert "error" in data
    assert "authentication" in data["error"].lower()


# ── 有用户上下文：正常执行 ───────────────────────────────

@pytest.mark.asyncio
async def test_rewrite_works_with_user_context():
    from mcp_server.tools.rewrite import rewrite_query

    token = _current_user_id.set(1)
    try:
        with patch("services.rag.pipeline.rewrite_query", new_callable=AsyncMock) as m:
            m.return_value = "改写后的查询"
            result = await rewrite_query("原问题")
        data = json.loads(result[0].text)
        assert data["rewritten"] == "改写后的查询"
        assert data["original"] == "原问题"
        m.assert_awaited_once()
    finally:
        _current_user_id.reset(token)


@pytest.mark.asyncio
async def test_rerank_works_with_user_context():
    from mcp_server.tools.rerank import rerank_results

    token = _current_user_id.set(1)
    try:
        fake_reranked = [
            {"text": "片段", "rerank_score": 0.9, "section": "经历", "chunk_index": 0},
        ]
        with patch("services.rag.retrieval.rerank", new_callable=AsyncMock, return_value=fake_reranked):
            result = await rerank_results("查询", '[{"text": "片段", "chunk_index": 0}]')
        data = json.loads(result[0].text)
        assert isinstance(data, list)
        assert data[0]["text"] == "片段"
    finally:
        _current_user_id.reset(token)
