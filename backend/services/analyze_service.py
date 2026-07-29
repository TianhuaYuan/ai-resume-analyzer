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

from core.retry import with_retry
from models.resume import Resume
from schemas.resume import ScoreDetail
from services.rag.pipeline import llm_generate
from services.resume_analysis_cache import (
    VALID_ANALYSIS_TYPES,
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
        "### ATS 匹配率: XX/100\n（简要分析）\n\n"
        "### 关键词覆盖率: XX/100\n（简要分析）\n\n"
        "### 技能密度: XX/100\n（简要分析）\n\n"
        "### 综合评价: XX/100\n（简要分析）\n"
    ),
}


def _parse_scores(analysis: str) -> ScoreDetail | None:
    r"""从 LLM 返回的评分文本中提取量化分数。

    Task 2.5: 支持多种 LLM 输出格式，按优先级匹配：
      1. "XX/100"     → 原始格式（含 "XX/100分" 变体）
      2. "XX分"       → 中文格式（不能紧跟在 "/" 后，避免匹配 "/100分" 中的 100）
      3. "score: XX"  → 英文键值
      4. "得分: XX"   → 中文键值

    约束：
      - 数字必须 0-100，过滤年份/ID 等误匹配（如 2024、12345）
        通过 `(?<!\d)` lookbehind 防止从长数字中截取 3 位（如 "2024" 取 "024"）
      - 至少 4 个有效分数，按出现顺序对应
        ats_match, keyword_coverage, skill_density, overall
      - 不足 4 个返回 None，由前端独立 fallback

    Args:
        analysis: LLM 返回的评分文本

    Returns:
        ScoreDetail 或 None
    """
    if not analysis:
        return None

    # Combined alternation pattern（finditer 一次扫描，避免多 pattern 分别匹配导致重复）
    # 顺序：XX/100 → XX分 → score: XX → 得分: XX
    # (?<!\d): 前面不能是数字，防止 "2024" 被部分匹配为 "024"
    # (?<!/): 前面不能是 "/"，防止 "/100分" 中的 100 被 XX分 模式重复匹配
    combined = (
        r"(?<!\d)(\d{1,3})\s*/\s*100"
        r"|(?<!\d)(?<!/)(\d{1,3})\s*分"
        r"|score\s*[:：]\s*(\d{1,3})"
        r"|得分\s*[:：]\s*(\d{1,3})"
    )

    all_scores: list[int] = []
    for m in re.finditer(combined, analysis):
        # alternation 中只有一个分组非 None
        for g in m.groups():
            if g is None:
                continue
            value = int(g)
            if value <= 100:
                all_scores.append(value)
            break  # 只处理第一个非 None 分组

    if len(all_scores) < 4:
        return None

    # 取前 4 个，按出现顺序对应 ATS/关键词/技能密度/综合
    return ScoreDetail(
        ats_match=all_scores[0],
        keyword_coverage=all_scores[1],
        skill_density=all_scores[2],
        overall=all_scores[3],
    )


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

    result: dict = {
        "resume_id": resume_id,
        "analysis_type": analysis_type,
        "analysis": analysis,
    }

    # score 类型：解析量化分数
    if analysis_type == "score":
        scores = _parse_scores(analysis)
        if scores is not None:
            result["scores"] = scores

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

    # 尝试批量读缓存
    cached = await get_full_analysis_cache(resume_id)
    if cached is not None:
        return {"resume_id": resume_id, **cached}

    # 缓存未命中 → LLM 补齐每种类型
    results: dict[str, dict] = {}
    for analysis_type in VALID_ANALYSIS_TYPES:
        r = await analyze_resume(db, user_id, resume_id, analysis_type)
        results[analysis_type] = r

    # 异步写回缓存（不阻塞响应）
    import asyncio
    asyncio.ensure_future(set_full_analysis_cache(resume_id, results))

    return {"resume_id": resume_id, **results}
