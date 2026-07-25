"""MCP Tool: rewrite_query — 改写查询以提高检索效果。"""

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
async def rewrite_query(
    question: str,
) -> list[TextContent]:
    """改写用户查询，使其更适合向量检索。

    Args:
        question: 用户的原始问题
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

    from services.rag.pipeline import rewrite_query as rag_rewrite

    if not question.strip():
        return [TextContent(type="text", text='{"error": "question cannot be empty"}')]

    try:
        rewritten = await asyncio.wait_for(
            rag_rewrite(question),
            timeout=MCP_HTTP_TIMEOUT.read,
        )
        return [
            TextContent(
                type="text",
                text=json.dumps(
                    {
                        "original": question,
                        "rewritten": rewritten,
                    },
                    ensure_ascii=False,
                ),
            )
        ]
    except Exception as e:
        logger.exception("rewrite_query failed")
        return [
            TextContent(
                type="text",
                text=json.dumps(
                    {
                        "original": question,
                        "rewritten": question,
                        "error": "Rewrite failed, returning original question",
                    },
                    ensure_ascii=False,
                ),
            )
        ]
