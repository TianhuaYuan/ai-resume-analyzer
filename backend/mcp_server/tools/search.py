"""MCP Tool: search_knowledge_base — 混合检索 + Rerank 精排。"""

import json
import logging

from mcp.types import TextContent

from mcp_server.server import get_current_user_id, mcp
from core.database import AsyncSessionLocal

logger = logging.getLogger(__name__)


@mcp.tool()
async def search_knowledge_base(
    query: str,
    resume_id: str,
    top_k: int = 5,
) -> list[TextContent]:
    """在简历知识库中搜索相关信息。

    Args:
        query: 搜索查询文本
        resume_id: 简历 ID（字符串数字）
        top_k: 返回结果数量，默认 5，最大 20
    """
    from sqlalchemy import select

    from models.resume import Resume
    from services.rag.retrieval import hybrid_search, rerank

    # SEC-002：MCP 工具必须校验用户身份，缺失上下文时拒绝而非静默放行。
    try:
        user_id = get_current_user_id()
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
        resume_id_int = int(resume_id)
    except (ValueError, TypeError):
        return [TextContent(type="text", text=f'{{"error": "Invalid resume_id: {resume_id}"}}')]

    top_k = max(1, min(top_k, 20))

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Resume).where(Resume.id == resume_id_int, Resume.user_id == user_id)
        )
        resume = result.scalar_one_or_none()

    if resume is None:
        return [
            TextContent(
                type="text", text=f'{{"error": "Resume {resume_id} not found or access denied"}}'
            )
        ]

    if resume.status != "ready":
        return [
            TextContent(
                type="text",
                text=f'{{"error": "Resume {resume_id} is not ready (status: {resume.status})"}}',
            )
        ]

    try:
        chunks = await hybrid_search(resume_id_int, query, top_k=20)
        if not chunks:
            return [
                TextContent(
                    type="text", text='{"results": [], "message": "No matching content found"}'
                )
            ]

        reranked = await rerank(query, chunks, top_k=top_k)

        results = [
            {
                "text": c["text"],
                "score": round(c.get("rerank_score", c.get("score", 0.0)), 4),
                "section": c.get("section", ""),
                "chunk_index": c.get("chunk_index", -1),
                "source": "knowledge_base",
            }
            for c in reranked
        ]

        return [TextContent(type="text", text=json.dumps(results, ensure_ascii=False))]
    except Exception as e:
        logger.exception("search_knowledge_base failed for resume %d", resume_id_int)
        return [TextContent(type="text", text='{"error": "Search failed, please try again later"}')]
