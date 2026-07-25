"""MCP Tool: rerank_results — 复用 Cross-Encoder 精排。

H6/M6 修复：原先使用 LLM 打分（llm_generate）做精排，属于重复实现且不稳定。
现改为直接复用 services.rag_service.rerank 中已有的 Cross-Encoder 精排能力。
"""

import asyncio
import json
import logging

import httpx
from mcp.types import TextContent

from core.config import settings
from mcp_server.server import get_current_user_id, mcp

logger = logging.getLogger(__name__)

MCP_HTTP_TIMEOUT = httpx.Timeout(settings.MCP_HTTP_TIMEOUT_TOTAL, connect=settings.MCP_HTTP_TIMEOUT_CONNECT)


@mcp.tool()
async def rerank_results(
    query: str,
    chunks: str,
    top_k: int = 5,
) -> list[TextContent]:
    """对搜索结果进行 Cross-Encoder 精排（复用 services.rag_service.rerank）。

    Args:
        query: 搜索查询文本
        chunks: 候选文档块列表（JSON 字符串），每块至少包含 "text" 字段
        top_k: 返回结果数量，默认 5
    """
    # SEC-002：MCP 工具必须校验用户身份，缺失上下文时拒绝而非静默放行。
    try:
        _user_id = get_current_user_id()
    except LookupError:
        return [
            TextContent(
                type="text",
                text=json.dumps(
                    {"error": "authentication required: missing user context"},
                    ensure_ascii=False,
                ),
            )
        ]

    try:
        chunk_list = json.loads(chunks) if isinstance(chunks, str) else chunks
    except json.JSONDecodeError:
        return [TextContent(type="text", text='{"error": "Invalid chunks JSON format"}')]

    if not chunk_list:
        return [TextContent(type="text", text='{"results": [], "message": "No chunks to rerank"}')]

    top_k = max(1, min(top_k, settings.DEFAULT_RERANK_TOP_K))

    try:
        # H6/M6：复用已有的 Cross-Encoder 精排，而非自实现 LLM 打分。
        from services.rag.retrieval import rerank as cross_encoder_rerank

        reranked = await asyncio.wait_for(
            cross_encoder_rerank(query, chunk_list, top_k=top_k),
            timeout=MCP_HTTP_TIMEOUT.read,
        )
    except Exception as e:
        logger.warning("rerank_results Cross-Encoder failed: %s", e)
        # 降级：保留原始顺序，给出保底分数，不向上抛异常。
        reranked = [
            {**c, "rerank_score": max(0.0, 1.0 - i * 0.1)} for i, c in enumerate(chunk_list)
        ][:top_k]

    results = [
        {
            "text": c.get("text", ""),
            "rerank_score": round(float(c.get("rerank_score", 1.0)), 4),
            "section": c.get("section", ""),
            "chunk_index": c.get("chunk_index", i),
        }
        for i, c in enumerate(reranked)
    ]

    return [TextContent(type="text", text=json.dumps(results, ensure_ascii=False))]
