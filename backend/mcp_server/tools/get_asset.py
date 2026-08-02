"""MCP Tool: get_asset — 按 (asset_type, asset_id) 读取资产源文本（T13）。

供 Agent 整文直读（绕过检索）与版本浏览前置取文本。强制 scope 归属校验。
"""

import json
import logging

from fastapi import HTTPException
from mcp.types import TextContent

from mcp_server.server import get_current_user_id, mcp
from mcp_server.tools.authz import assert_user_owns_assets
from core.database import AsyncSessionLocal
from services.rag.asset_source import resolve_asset_text

logger = logging.getLogger(__name__)


@mcp.tool()
async def get_asset(
    asset_id: str,
    asset_type: str = "resume",
    version: str = None,
) -> list[TextContent]:
    """读取指定资产的源文本。

    Args:
        asset_id: 资产 ID（字符串数字）
        asset_type: 资产类型（resume / jd / interview / note）
        version: 预留版本参数；当前返回已落库的最新文本（版本化历史由 T18 版本浏览提供）
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

    try:
        asset_id_int = int(asset_id)
    except (ValueError, TypeError):
        return [TextContent(type="text", text=f'{{"error": "Invalid asset_id: {asset_id}"}}')]

    # SEC-003（T13）：资产必须归属当前用户，越权 403。
    try:
        await assert_user_owns_assets(user_id, {asset_type: [asset_id_int]})
    except HTTPException as e:
        return [TextContent(type="text", text=json.dumps({"error": e.detail}, ensure_ascii=False))]

    async with AsyncSessionLocal() as db:
        text = await resolve_asset_text(db, asset_type, asset_id_int)

    if text is None:
        return [
            TextContent(
                type="text",
                text=json.dumps(
                    {"error": f"Asset {asset_type}/{asset_id} not found or access denied"}
                ),
            )
        ]

    return [
        TextContent(
            type="text",
            text=json.dumps(
                {
                    "asset_id": asset_id_int,
                    "asset_type": asset_type,
                    "version": version,
                    "text": text,
                },
                ensure_ascii=False,
            ),
        )
    ]
