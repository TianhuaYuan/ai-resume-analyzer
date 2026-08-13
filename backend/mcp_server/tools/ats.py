"""MCP Tool: ats_audit — ATS 可读性审计（调 P0-A ats_audit_service）。

薄包装：调 ats_audit_service.audit_resume，捕获异常转 TextContent 错误 JSON。
"""

import json
import logging

from mcp.types import TextContent

from mcp_server.server import get_current_user_id, mcp
from core.database import AsyncSessionLocal

logger = logging.getLogger(__name__)


@mcp.tool()
async def ats_audit(resume_id: str) -> list[TextContent]:
    """审计简历的 ATS 可读性问题（乱码、特殊符号、表格、空白段等）。

    返回结构化问题清单和 ATS 可读性评分。
    纯本地规则引擎，零 LLM 调用。

    Args:
        resume_id: 简历 ID（字符串数字）
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

    try:
        from services.ats_audit_service import audit_resume

        async with AsyncSessionLocal() as db:
            result = await audit_resume(db, user_id, resume_id_int)
        return [
            TextContent(
                type="text",
                text=result.model_dump_json(indent=2),
            )
        ]
    except Exception as e:
        detail = getattr(e, "detail", str(e))
        return [TextContent(type="text", text=json.dumps({"error": detail}, ensure_ascii=False))]
