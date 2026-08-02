"""MCP Tool: answer_from_index — 按 scope 原子生成答案（T13）。

把 agentic RAG 的「检索 → 反思 → 生成」折叠为单个原子工具，
取代旧 mcp_graph / mcp_nodes 的节点级 MCP 调用链（T14）。
调用链：scope 鉴权 → run_answer_from_index → 结构化结果。
"""

import json
import logging

from fastapi import HTTPException
from mcp.types import TextContent

from mcp_server.server import get_current_user_id, mcp
from mcp_server.tools.authz import assert_user_owns_assets

logger = logging.getLogger(__name__)


@mcp.tool()
async def answer_from_index(
    query: str,
    scope: str,
    top_k: int = 5,
) -> list[TextContent]:
    """基于知识资产库（scope）生成答案（原子工具：检索+反思+生成一次完成）。

    Args:
        query: 用户问题
        scope: 资产范围 JSON 字符串，如 '{"resume": [1,2], "jd": [5]}'
        top_k: 预留参数（当前由 runner 内部策略控制，仅做上限约束）
    """
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

    # SEC-003（T13）：scope 内每个资产都必须归属当前用户，越权 403。
    try:
        normalized_scope = await assert_user_owns_assets(user_id, scope)
    except HTTPException as e:
        return [TextContent(type="text", text=json.dumps({"error": e.detail}, ensure_ascii=False))]

    if not query.strip():
        return [TextContent(type="text", text='{"error": "query cannot be empty"}')]

    from services.agentic_rag.runner import run_answer_from_index

    try:
        result = await run_answer_from_index(
            user_id=user_id,
            scope=normalized_scope,
            question=query,
        )
    except Exception:
        logger.exception("answer_from_index failed for scope=%s", normalized_scope)
        return [
            TextContent(
                type="text",
                text=json.dumps(
                    {"error": "Answer generation failed, please try again later"},
                    ensure_ascii=False,
                ),
            )
        ]

    return [
        TextContent(
            type="text",
            text=json.dumps(
                {
                    "answer": result.get("answer", ""),
                    "sources": result.get("sources", []),
                    "eval_score": result.get("eval_score", 0.0),
                    "reflection_round": result.get("reflection_round", 0),
                    "trace": result.get("trace", {}),
                },
                ensure_ascii=False,
            ),
        )
    ]
