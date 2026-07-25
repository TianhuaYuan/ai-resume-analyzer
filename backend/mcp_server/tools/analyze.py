"""MCP Tool: analyze_resume - 分析简历内容。

薄包装：调 analyze_service.analyze_resume，捕获 HTTPException 转 TextContent 错误 JSON。
行为与重构前完全一致。
"""

import json
import logging

from mcp.types import TextContent

from mcp_server.server import get_current_user_id, mcp
from services.analyze_service import analyze_resume as service_analyze_resume, _ANALYSIS_PROMPTS
from core.database import AsyncSessionLocal

logger = logging.getLogger(__name__)


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
