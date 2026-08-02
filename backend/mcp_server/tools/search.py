"""MCP Tool: 知识库检索（T13）。

- ``search_index``            泛化工具：按 scope（asset_type → asset_ids）混合检索，强制 scope 鉴权。
- ``search_knowledge_base``   旧工具保留为别名：内部 scope={resume: [resume_id]}，行为收敛到 search_index。
"""

import json
import logging

from fastapi import HTTPException
from mcp.types import TextContent

from mcp_server.server import get_current_user_id, mcp
from mcp_server.tools.authz import assert_user_owns_assets
from services.rag.asset_source import ASSET_TYPE_RESUME

logger = logging.getLogger(__name__)

_MAX_TOP_K = 20


def _auth_error_text() -> list[TextContent]:
    return [
        TextContent(
            type="text",
            text=json.dumps(
                {"error": "authentication required: missing user context"},
                ensure_ascii=False,
            ),
        )
    ]


def _parse_filters(filters: str) -> dict:
    """解析预留过滤参数（当前仅作校验；版本过滤由后端 is_latest 控制）。"""
    if not filters or not filters.strip():
        return {}
    try:
        parsed = json.loads(filters)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid filters: not valid JSON")
    if not isinstance(parsed, dict):
        raise HTTPException(status_code=400, detail="Invalid filters: expected object")
    return parsed


@mcp.tool()
async def search_index(
    query: str,
    scope: str,
    filters: str = "{}",
    top_k: int = 5,
) -> list[TextContent]:
    """在知识资产库（多类型 scope）中混合检索。

    Args:
        query: 搜索查询文本
        scope: 资产范围 JSON 字符串，如 '{"resume": [1,2], "jd": [5]}'
        filters: 预留过滤条件 JSON（版本过滤由后端 is_latest 默认控制，暂不支持外部覆盖）
        top_k: 返回结果数量，默认 5，最大 20
    """
    # SEC-002：MCP 工具必须校验用户身份，缺失上下文时拒绝而非静默放行。
    try:
        user_id = get_current_user_id()
    except LookupError:
        return _auth_error_text()

    # SEC-003（T13）：scope 内每个资产都必须归属当前用户，越权 403。
    try:
        normalized_scope = await assert_user_owns_assets(user_id, scope)
        _parse_filters(filters)  # 仅校验格式，版本过滤走后端 is_latest
    except HTTPException as e:
        return [TextContent(type="text", text=json.dumps({"error": e.detail}, ensure_ascii=False))]

    top_k = max(1, min(top_k, _MAX_TOP_K))

    from services.rag.retrieval import hybrid_search_corpus

    try:
        chunks = await hybrid_search_corpus(user_id, normalized_scope, query, top_k=top_k)
        if not chunks:
            return [
                TextContent(
                    type="text", text='{"results": [], "message": "No matching content found"}'
                )
            ]

        results = [
            {
                "text": c["text"],
                "score": round(float(c.get("score", c.get("rerank_score", 0.0))), 4),
                "section": c.get("section", ""),
                "chunk_index": c.get("chunk_index", -1),
                "asset_id": c.get("asset_id"),
                "version": c.get("version"),
                "source": c.get("source", "hybrid"),
            }
            for c in chunks
        ]

        return [TextContent(type="text", text=json.dumps(results, ensure_ascii=False))]
    except Exception:
        logger.exception("search_index failed for scope=%s", normalized_scope)
        return [TextContent(type="text", text='{"error": "Search failed, please try again later"}')]


@mcp.tool()
async def search_knowledge_base(
    query: str,
    resume_id: str,
    top_k: int = 5,
) -> list[TextContent]:
    """在简历知识库中搜索相关信息（search_index 的特例别名）。

    Args:
        query: 搜索查询文本
        resume_id: 简历 ID（字符串数字）
        top_k: 返回结果数量，默认 5，最大 20
    """
    scope = json.dumps({ASSET_TYPE_RESUME: [resume_id]}, ensure_ascii=False)
    return await search_index(query, scope, top_k=top_k)
