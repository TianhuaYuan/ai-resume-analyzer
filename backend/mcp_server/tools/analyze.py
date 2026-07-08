"""MCP Tool: analyze_resume — 分析简历内容。"""
import logging

from mcp.types import TextContent

from mcp_server.server import get_current_user_id, mcp

logger = logging.getLogger(__name__)

_ANALYSIS_PROMPTS = {
    "summary": (
        "请对以下简历内容进行全面总结，包括：\n"
        "1. 个人基本信息（姓名、联系方式）\n"
        "2. 教育背景\n"
        "3. 工作/实习经历概览\n"
        "4. 核心技能\n"
        "5. 整体评价（2-3句话）\n"
        "请用简洁的结构化格式输出。"
    ),
    "skills": (
        "请从以下简历中提取所有技能信息，按以下类别分类：\n"
        "1. 编程语言\n"
        "2. 框架/工具\n"
        "3. 软技能\n"
        "4. 其他技能\n"
        "如果简历中没有明确的技能描述，请从工作经历和项目经历中推断。"
    ),
    "experience": (
        "请从以下简历中提取所有工作和实习经历，按时间倒序列出：\n"
        "每段经历包括：公司/组织名称、职位、时间段、主要职责和成就。\n"
        "如果简历中没有工作经历，请说明。"
    ),
}


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
    import json

    from sqlalchemy import select

    from core.database import AsyncSessionLocal
    from core.retry import with_retry
    from models.resume import Resume
    from services.rag_service import llm_generate

    user_id = get_current_user_id()

    try:
        resume_id_int = int(resume_id)
    except (ValueError, TypeError):
        return [TextContent(type="text", text=f'{{"error": "Invalid resume_id: {resume_id}"}}')]

    if analysis_type not in _ANALYSIS_PROMPTS:
        import json

        valid = ", ".join(_ANALYSIS_PROMPTS.keys())
        return [TextContent(
            type="text",
            text=json.dumps({"error": f"Invalid analysis_type: {analysis_type}. Valid types: {valid}"}),
        )]

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Resume).where(Resume.id == resume_id_int, Resume.user_id == user_id)
        )
        resume = result.scalar_one_or_none()

    if resume is None:
        return [TextContent(type="text", text=f'{{"error": "Resume {resume_id} not found or access denied"}}')]

    if resume.status != "ready":
        return [TextContent(
            type="text",
            text=f'{{"error": "Resume {resume_id} is not ready (status: {resume.status})"}}',
        )]

    parsed_text = resume.parsed_text
    if not parsed_text:
        try:
            from utils.file_parser import parse_resume

            parsed_text = await with_retry(
                lambda: parse_resume(resume.file_path), fallback=""
            )
        except Exception as e:
            logger.warning("Failed to parse resume file %s: %s", resume.file_path, e)
            return [TextContent(type="text", text=f'{{"error": "Failed to read resume content: {e}"}}')]

    if not parsed_text.strip():
        return [TextContent(type="text", text='{"error": "Resume content is empty"}')]

    system_prompt = _ANALYSIS_PROMPTS[analysis_type]
    user_prompt = f"简历内容：\n\n{parsed_text}\n\n请按要求进行分析。"

    try:
        analysis = await with_retry(
            llm_generate, system_prompt, user_prompt, fallback="分析失败，请稍后重试"
        )
        return [TextContent(type="text", text=json.dumps({
            "resume_id": resume_id_int,
            "analysis_type": analysis_type,
            "analysis": analysis,
        }, ensure_ascii=False))]
    except Exception as e:
        logger.exception("analyze_resume failed for resume %d", resume_id_int)
        return [TextContent(type="text", text=f'{{"error": "Analysis failed: {e}"}}')]
