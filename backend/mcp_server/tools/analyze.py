"""MCP Tool: analyze_resume / analyze_asset — 分析资产内容。

- ``analyze_resume``  旧工具（保留）：只分析简历（resume_id）。
- ``analyze_asset``   T13 泛化别名：按 (asset_id, asset_type) 分析，先做 scope 归属校验。

薄包装：调 analyze_service.analyze_resume，捕获 HTTPException 转 TextContent 错误 JSON。
行为与重构前完全一致。
"""

import json
import logging

from fastapi import HTTPException
from mcp.types import TextContent

from mcp_server.server import get_current_user_id, mcp
from mcp_server.tools.authz import assert_user_owns_assets
from services.analyze_service import analyze_resume as service_analyze_resume, _ANALYSIS_PROMPTS
from services.rag.asset_source import ASSET_TYPE_RESUME
from core.database import AsyncSessionLocal

logger = logging.getLogger(__name__)


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


@mcp.tool()
async def analyze_resume(
    resume_id: str,
    analysis_type: str = "summary",
) -> list[TextContent]:
    """分析简历内容，提取关键信息。

    Args:
        resume_id: 简历 ID（字符串数字）
        analysis_type: 分析类型（summary/skills/experience）
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
        resume_id_int = int(resume_id)
    except (ValueError, TypeError):
        return [TextContent(type="text", text=f'{{"error": "Invalid resume_id: {resume_id}"}}')]

    if analysis_type not in _ANALYSIS_PROMPTS:
        valid = ", ".join(_ANALYSIS_PROMPTS.keys())
        return [
            TextContent(
                type="text",
                text=json.dumps(
                    {"error": f"Invalid analysis_type: {analysis_type}. Valid types: {valid}"}
                ),
            )
        ]

    async with AsyncSessionLocal() as db:
        try:
            result = await service_analyze_resume(db, user_id, resume_id_int, analysis_type)
        except Exception as e:
            # service 抛 HTTPException 或其他异常，统一转 MCP 错误格式
            detail = getattr(e, "detail", str(e))
            return [TextContent(type="text", text=json.dumps({"error": detail}))]

    return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False))]


@mcp.tool()
async def analyze_asset(
    asset_id: str,
    asset_type: str = "resume",
    analysis_type: str = "summary",
) -> list[TextContent]:
    """按 (asset_type, asset_id) 分析资产内容（analyze_resume 的 T13 泛化别名）。

    Args:
        asset_id: 资产 ID（字符串数字）
        asset_type: 资产类型。当前分析服务只支持 resume；jd/interview/note 待后续
            泛化 analyze_service 后接入，此处返回明确的暂不支持提示。
        analysis_type: 分析类型（summary/skills/experience/score）
    """
    # SEC-002：MCP 工具必须校验用户身份，缺失上下文时拒绝而非静默放行。
    try:
        user_id = get_current_user_id()
    except LookupError:
        return _auth_error_text()

    try:
        asset_id_int = int(asset_id)
    except (ValueError, TypeError):
        return [TextContent(type="text", text=f'{{"error": "Invalid asset_id: {asset_id}"}}')]

    # SEC-003：资产必须归属当前用户，越权 403。
    try:
        await assert_user_owns_assets(user_id, {asset_type: [asset_id_int]})
    except HTTPException as e:
        return [TextContent(type="text", text=json.dumps({"error": e.detail}, ensure_ascii=False))]

    if asset_type != ASSET_TYPE_RESUME:
        # 泛化方向：analyze_service 目前只支持 resume（LLM prompt / 缓存都按 resume 键）。
        # 泛化需把 _ANALYSIS_PROMPTS / 分析缓存从 resume_id 键改为 (asset_type, asset_id) 键。
        return [
            TextContent(
                type="text",
                text=json.dumps(
                    {
                        "error": (
                            f"analysis for asset_type='{asset_type}' is not supported yet; "
                            "currently only 'resume' is supported "
                        )
                    },
                    ensure_ascii=False,
                ),
            )
        ]

    if analysis_type not in _ANALYSIS_PROMPTS:
        valid = ", ".join(_ANALYSIS_PROMPTS.keys())
        return [
            TextContent(
                type="text",
                text=json.dumps(
                    {"error": f"Invalid analysis_type: {analysis_type}. Valid types: {valid}"}
                ),
            )
        ]

    async with AsyncSessionLocal() as db:
        try:
            result = await service_analyze_resume(db, user_id, asset_id_int, analysis_type)
        except Exception as e:
            # service 抛 HTTPException 或其他异常，统一转 MCP 错误格式
            detail = getattr(e, "detail", str(e))
            return [TextContent(type="text", text=json.dumps({"error": detail}))]

    return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False))]
