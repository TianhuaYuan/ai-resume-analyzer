"""MCP Tool: rewrite_query — 改写查询以提高检索效果。"""
import json
import logging

from mcp.types import TextContent

from mcp_server.server import mcp

logger = logging.getLogger(__name__)


@mcp.tool()
async def rewrite_query(
    question: str,
    context: str = "",
) -> list[TextContent]:
    """改写用户查询，使其更适合向量检索。

    Args:
        question: 用户的原始问题
        context: 可选的上下文信息，用于辅助改写
    """
    from services.rag_service import rewrite_query as rag_rewrite

    if not question.strip():
        return [TextContent(type="text", text='{"error": "question cannot be empty"}')]

    try:
        rewritten = await rag_rewrite(question)
        return [TextContent(type="text", text=json.dumps({
            "original": question,
            "rewritten": rewritten,
        }, ensure_ascii=False))]
    except Exception as e:
        logger.exception("rewrite_query failed")
        return [TextContent(type="text", text=json.dumps({
            "original": question,
            "rewritten": question,
            "error": f"Rewrite failed, returning original: {e}",
        }, ensure_ascii=False))]
