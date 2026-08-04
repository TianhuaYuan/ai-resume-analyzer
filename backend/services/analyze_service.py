"""简历智能分析服务。

从 mcp_server/tools/analyze.py 抽取的共享逻辑，供 MCP 工具和 REST 端点复用。
MCP 工具捕获 HTTPException 转 TextContent 错误 JSON，REST 端点直接抛出。
"""

import logging
import re
from typing import Literal

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.retry import with_retry
from models.resume import Resume
from schemas.resume import ScoreDetail
from services.rag.pipeline import llm_generate, get_chat_client
from services.rag.usage import record_llm_usage
from services.resume_analysis_cache import (
    VALID_ANALYSIS_TYPES,
    get_analysis_cache,
    get_full_analysis_cache,
    set_full_analysis_cache,
)

logger = logging.getLogger(__name__)

AnalysisType = Literal["summary", "skills", "experience", "score"]

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
    "score": (
        "你是一个专业的简历评分专家。请从以下四个维度对简历进行量化评分：\n\n"
        "1. **ATS 匹配率**（0-100）：简历结构是否清晰、关键词是否丰富、"
        "格式是否 ATS（Applicant Tracking System）友好\n"
        "2. **关键词覆盖率**（0-100）：技术关键词、行业术语的覆盖广度\n"
        "3. **技能密度**（0-100）：技能的深度和广度，是否有跨领域技能\n"
        "4. **综合评价**（0-100）：综合以上维度的加权评分\n\n"
        "请严格按以下格式输出：\n\n"
        "## 综合评分\n\n"
    ),
}


def _parse_scores(analysis: str) -> ScoreDetail | None:
    r"""从 LLM 返回的评分文本中提取量化分数。

    Task 2.5: 支持多种 LLM 输出格式，按优先级匹配：
    1. Markdown 表格（最常见）
    2. JSON 格式
    3. 键值对 / 分节标题（中英文标签：XX/100、XX分、score: XX、得分: XX，标签与数字可跨行）
    4. 裸数字序列（无标签，按出现顺序取前 4 个）

    非法分数（>100，如年份/ID）会被过滤，导致有效分数不足 4 个时返回 None。
    """
    if not analysis:
        return None

    all_scores: list[int] = []

    # 1. 尝试从 Markdown 表格中提取
    table_pattern = re.compile(
        r"\|\s*(?:ATS|关键词|技能密度|综合|评价)\s*\|\s*(\d+)\s*\|"
    )
    all_scores = [int(m.group(1)) for m in table_pattern.finditer(analysis)]

    # 2. 尝试 JSON 格式
    if not all_scores:
        json_pattern = re.compile(
            r'"(?:ats_match|keyword_coverage|skill_density|overall)"\s*:\s*(\d+)'
        )
        all_scores = [int(m.group(1)) for m in json_pattern.finditer(analysis)]

    # 3. 尝试键值对 / 分节标题格式（标签后在本行或紧随数行内取第一个数字）
    if not all_scores:
        label_pattern = re.compile(
            r"(?:ATS\s*匹配率|关键词覆盖率|技能密度|综合评价|"
            r"ATS\s*score|keyword\s*score|skill\s*score|overall\s*score|"
            r"ATS\s*得分|关键词\s*得分|技能\s*得分|综合\s*得分)"
        )
        for m in label_pattern.finditer(analysis):
            tail = analysis[m.end():m.end() + 80]
            num = re.search(r"(\d+)", tail)
            if num:
                all_scores.append(int(num.group(1)))

    # 4. 兜底：无标签裸数字序列（如 "85/100\n90/100\n78/100\n82/100"）
    if not all_scores:
        bare_pattern = re.compile(r"(?:^|\D)(\d{1,3})(?:/100|分)?")
        all_scores = [int(m.group(1)) for m in bare_pattern.finditer(analysis)]

    # 过滤非法分数（年份/ID 等 >100 的数字不是分数）
    valid_scores = [s for s in all_scores if 0 <= s <= 100]
    if len(valid_scores) < 4:
        return None

    return ScoreDetail(
        ats_match=valid_scores[0],
        keyword_coverage=valid_scores[1],
        skill_density=valid_scores[2],
        overall=valid_scores[3],
    )


async def analyze_resume(
    db: AsyncSession,
    user_id: int,
    resume_id: int,
    analysis_type: str,
) -> dict:
    """分析简历内容，直接调 Chat API 并捕获 token 消耗。"""
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

    # 优先返回缓存结果，避免重复 LLM 调用
    cached = await get_analysis_cache(resume_id, analysis_type)
    if cached is not None:
        logger.info("分析缓存命中: resume_id=%d, type=%s", resume_id, analysis_type)
        return {
            "resume_id": resume_id,
            "analysis_type": analysis_type,
            "analysis": cached.get("analysis", ""),
            "scores": cached.get("scores"),
            "cached": True,
        }

    parsed_text = resume.parsed_text
    if not parsed_text:
        try:
            from utils.file_parser import parse_resume

            parsed_text = await with_retry(parse_resume, resume.file_path, fallback="")
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
        client = get_chat_client()
        response = await client.chat.completions.create(
            model=settings.CHAT_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.3,
        )
        analysis = (response.choices[0].message.content or "").strip()
        usage_info = {}
        if hasattr(response, "usage") and response.usage:
            pt = getattr(response.usage, "prompt_tokens", 0) or 0
            ct = getattr(response.usage, "completion_tokens", 0) or 0
            usage_info = {"total_tokens": pt + ct, "prompt_tokens": pt, "completion_tokens": ct}
            # T3: 统一记账
            await record_llm_usage(user_id, pt, ct)
            logger.info("分析 token: type=%s, prompt=%d, completion=%d, total=%d",
                        analysis_type, pt, ct, pt + ct)
        else:
            logger.info("分析无 usage 返回: type=%s, hasattr=%s",
                        analysis_type, hasattr(response, "usage"))
    except Exception as e:
        logger.exception("analyze_resume failed for resume %d", resume_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"分析失败: {e}",
        )

    result: dict = {
        "resume_id": resume_id,
        "analysis_type": analysis_type,
        "analysis": analysis,
        "usage": usage_info,
    }

    # score 类型：解析量化分数
    if analysis_type == "score":
        scores = _parse_scores(analysis)
        if scores is not None:
            result["scores"] = scores.model_dump()

    return result


async def get_full_analysis(
    db: AsyncSession,
    user_id: int,
    resume_id: int,
) -> dict:
    """获取一份简历的完整分析结果（4 种类型）。

    优先批量读 Redis 缓存，全部命中时不调用 LLM。
    缓存缺失的类型自动调用 analyze_resume 补齐（同时写入缓存）。

    Returns:
        {
            "resume_id": int,
            "summary": dict,
            "skills": dict,
            "experience": dict,
            "score": dict,
        }
    """
    # 校验简历归属 + 状态
    result = await db.execute(
        select(Resume).where(Resume.id == resume_id, Resume.user_id == user_id)
    )
    resume = result.scalar_one_or_none()
    if resume is None:
        raise HTTPException(status_code=404, detail="简历不存在或无权访问")
    if resume.status != "ready":
        raise HTTPException(
            status_code=409,
            detail=f"简历未就绪（当前状态: {resume.status}）",
        )

    # 优先批量读缓存
    cached = await get_full_analysis_cache(resume_id)
    if cached is not None:
        return {"resume_id": resume_id, **cached}

    # 缓存缺失，逐个调用 LLM
    results: dict[str, dict] = {}
    for atype in VALID_ANALYSIS_TYPES:
        try:
            r = await analyze_resume(db, user_id, resume_id, atype)
            results[atype] = r
        except Exception as e:
            logger.error("get_full_analysis 补齐 %s 失败: %s", atype, e)
            raise

    # 写入完整缓存
    await set_full_analysis_cache(resume_id, results)
    return {"resume_id": resume_id, **results}
