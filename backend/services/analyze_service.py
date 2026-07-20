"""简历智能分析服务。

从 mcp_server/tools/analyze.py 抽取的共享逻辑，供 MCP 工具和 REST 端点复用。
MCP 工具捕获 HTTPException 转 TextContent 错误 JSON，REST 端点直接抛出。
"""

import logging
from typing import Literal

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.retry import with_retry
from models.resume import Resume
from services.rag.pipeline import llm_generate

logger = logging.getLogger(__name__)

AnalysisType = Literal["summary", "skills", "experience"]

_ANALYSIS_PROMPTS: dict[str, str] = {
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


async def analyze_resume(
    db: AsyncSession,
    user_id: int,
    resume_id: int,
    analysis_type: str,
) -> dict:
    """分析简历内容，返回 {"resume_id", "analysis_type", "analysis"}。

    Raises:
        HTTPException:
            422 非法 analysis_type 或简历内容为空
            404 简历不存在或非本人
            409 简历未就绪
            500 LLM 调用失败
    """
    if analysis_type not in _ANALYSIS_PROMPTS:
        valid = ", ".join(_ANALYSIS_PROMPTS.keys())
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"非法 analysis_type: {analysis_type}。合法值: {valid}",
        )

    result = await db.execute(
        select(Resume).where(Resume.id == resume_id, Resume.user_id == user_id)
    )
    resume = result.scalar_one_or_none()
    if resume is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="简历不存在或无权访问",
        )

    if resume.status != "ready":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"简历未就绪（当前状态: {resume.status}）",
        )

    parsed_text = resume.parsed_text
    if not parsed_text:
        try:
            from utils.file_parser import parse_resume

            parsed_text = await with_retry(lambda: parse_resume(resume.file_path), fallback="")
        except Exception as e:
            logger.warning("Failed to parse resume file %s: %s", resume.file_path, e)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"读取简历内容失败: {e}",
            )

    if not parsed_text.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="简历内容为空",
        )

    system_prompt = _ANALYSIS_PROMPTS[analysis_type]
    user_prompt = f"简历内容：\n\n{parsed_text}\n\n请按要求进行分析。"

    try:
        analysis = await with_retry(
            llm_generate, system_prompt, user_prompt, fallback="分析失败，请稍后重试"
        )
    except Exception as e:
        logger.exception("analyze_resume failed for resume %d", resume_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"分析失败: {e}",
        )

    return {
        "resume_id": resume_id,
        "analysis_type": analysis_type,
        "analysis": analysis,
    }
