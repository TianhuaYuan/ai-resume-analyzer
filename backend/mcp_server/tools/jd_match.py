"""MCP Tool: match_job_description — 简历与 JD 匹配分析（调 match_jd_service）。

薄包装：调 match_jd_service.match_jd，捕获异常转 TextContent 错误 JSON。
"""

import json
import logging

from mcp.types import TextContent

from mcp_server.server import get_current_user_id, mcp
from core.database import AsyncSessionLocal

logger = logging.getLogger(__name__)


@mcp.tool()
async def match_job_description(
    resume_id: str,
    jd_text: str,
) -> list[TextContent]:
    """将简历与职位描述（JD）进行匹配分析。

    返回匹配分数、匹配/缺失关键词、差距分析和改进建议。
    使用 LLM 进行结构化分析（JSON-first 输出，失败降级为 markdown）。

    Args:
        resume_id: 简历 ID（字符串数字）
        jd_text: 职位描述文本
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

    if not jd_text or not jd_text.strip():
        return [
            TextContent(
                type="text",
                text=json.dumps(
                    {"error": "jd_text cannot be empty"},
                    ensure_ascii=False,
                ),
            )
        ]

    try:
        from services.match_jd_service import match_jd

        async with AsyncSessionLocal() as db:
            result = await match_jd(db, user_id, resume_id_int, jd_text)
        return [
            TextContent(
                type="text",
                text=json.dumps(result, ensure_ascii=False, indent=2),
            )
        ]
    except Exception as e:
        detail = getattr(e, "detail", str(e))
        return [TextContent(type="text", text=json.dumps({"error": detail}, ensure_ascii=False))]
