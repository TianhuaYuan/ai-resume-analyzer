"""JD-Resume 匹配分析服务。

将简历内容与 JD（Job Description）文本进行 LLM 对比分析，
返回匹配分数、匹配点、差距分析和改进建议。

A3 评分契约升级（Magic-Resume fit-report.ts 对照）：JSON-first 结构化输出
（score/matched/missing/gaps/reason），解析失败降级为原 markdown 分析。
"""

import json
import logging

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.retry import with_retry
from models.resume import Resume
from schemas.resume import derive_band
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

# Magic-Resume FitReport 契约对照：结构化 JSON 输出（JSON-first）
_STRUCTURED_SYSTEM = (
    "你是一个专业的招聘分析师。将简历与 JD 对比分析。\n"
    "严格输出 JSON 对象（不要 Markdown，不要 ```json 包裹）：\n"
    '{"score": <0-100 整数>,\n'
    ' "matched": ["简历中与 JD 匹配的技能/经历关键词", ...],\n'
    ' "missing": ["JD 要求但简历中缺失的关键词/技能", ...],\n'
    ' "gaps": ["针对缺失的低成本改进建议", ...],\n'
    ' "reason": "<一句话匹配总结>"}'
)


def _extract_json_object(raw: str) -> dict:
    """抗截断 JSON 对象提取（SmartResume {..} 区间 + 三层降级）。"""
    start, end = raw.find("{"), raw.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("无 JSON 对象")
    content = raw[start : end + 1]
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        fixed = content.replace("'", '"').replace("True", "true").replace("False", "false")
        return json.loads(fixed)


async def _structured_match(user_prompt: str, user_id: int) -> dict | None:
    """结构化匹配（JSON-first）：失败返回 None → 调用方降级 markdown。"""
    try:
        raw = await with_retry(
            llm_generate,
            _STRUCTURED_SYSTEM,
            user_prompt,
            user_id=user_id,
            fallback="",
            max_retries=1,
        )
        data = _extract_json_object(raw)
        score = int(data.get("score", 0))
        score = max(0, min(100, score))  # 0-100 夹紧
        return {
            "score": score,
            "band": derive_band(score),
            "matched": [str(s) for s in data.get("matched", []) if str(s).strip()][:10],
            "missing": [str(s) for s in data.get("missing", []) if str(s).strip()][:10],
            "gaps": [str(s) for s in data.get("gaps", []) if str(s).strip()][:5],
            "reason": str(data.get("reason", "")).strip(),
        }
    except Exception as e:
        logger.warning("JD 结构化匹配失败（降级 markdown）: %s", e)
        return None


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
        f"简历内容：\n\n{parsed_text}\n\n职位描述（JD）：\n\n{jd_text}\n\n请按要求进行匹配分析。"
    )

    # JSON-first 结构化匹配（Magic-Resume FitReport 契约对照）：
    # LLM 一次输出 score/matched/missing/gaps/reason，失败降级 markdown 分析
    structured = await _structured_match(user_prompt, user_id)
    if structured is not None:
        reason = structured["reason"] or (
            f"匹配度 {structured['score']} 分：匹配 {len(structured['matched'])} 项，"
            f"缺失 {len(structured['missing'])} 项"
        )
        return {
            "resume_id": resume_id,
            "analysis": reason,
            "scores": {"overall": structured["score"], "band": structured["band"]},
            "matched_keywords": structured["matched"],
            "missing_keywords": structured["missing"],
            "gaps": structured["gaps"],
        }

    try:
        analysis = await with_retry(
            llm_generate,
            _SYSTEM_PROMPT,
            user_prompt,
            user_id=user_id,
            fallback="分析失败，请稍后重试",
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
