"""JD-Resume 匹配分析服务。

将简历内容与 JD（Job Description）文本进行 LLM 对比分析，
返回匹配分数、匹配点、差距分析和改进建议。
"""

import logging

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.retry import with_retry
from models.resume import Resume
from services.rag.pipeline import llm_generate

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "你是一个专业的招聘分析师。请将以下简历内容与职位描述（JD）进行对比分析。\n\n"
    "请按以下格式输出：\n"
    "## 匹配分数\n（0-100 分，整数）\n\n"
    "## 匹配点\n（列出简历中与 JD 要求匹配的技能、经验和经历）\n\n"
    "## 差距分析\n（列出 JD 要求但简历中缺失或不足的技能/经验）\n\n"
    "## 改进建议\n（针对差距给出具体可执行的改进建议）"
)


async def match_jd(
    db: AsyncSession,
    user_id: int,
    resume_id: int,
    jd_text: str,
) -> dict:
    """分析简历与 JD 的匹配度，返回 {"resume_id", "analysis"}。

    Raises:
        HTTPException:
            422 JD 文本为空
            404 简历不存在或非本人
            409 简历未就绪
            500 LLM 调用失败
    """
    if not jd_text.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="JD 文本不能为空",
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
    if not parsed_text.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="简历内容为空",
        )

    user_prompt = (
        f"简历内容：\n\n{parsed_text}\n\n"
        f"职位描述（JD）：\n\n{jd_text}\n\n"
        f"请按要求进行匹配分析。"
    )

    try:
        analysis = await with_retry(
            llm_generate, _SYSTEM_PROMPT, user_prompt, fallback="分析失败，请稍后重试"
        )
    except Exception as e:
        logger.exception("match_jd failed for resume %d", resume_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"匹配分析失败: {e}",
        )

    return {
        "resume_id": resume_id,
        "analysis": analysis,
    }
