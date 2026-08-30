"""简历智能分析服务。

从 mcp_server/tools/analyze.py 抽取的共享逻辑，供 MCP 工具和 REST 端点复用。
MCP 工具捕获 HTTPException 转 TextContent 错误 JSON，REST 端点直接抛出。
"""

import asyncio
import json
import logging
import re
from typing import Literal

from fastapi import HTTPException, status
from pydantic import ValidationError
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

# ── 对抗二评（DeepInterview verifier.py 整体移植）──────────────────
# 只对低于此阈值的维度做二评（对齐 _VERIFY_LEVELS weak/developing 语义）
VERIFY_SCORE_THRESHOLD = 60
# 每个二评 LLM 调用的墙钟上限
VERIFY_TIMEOUT = 30

_VERIFY_SYSTEM = (
    "你是一个怀疑派二次评审，审计简历评分是否过高或过低（over/under-scoring）。\n"
    "给定一个评分维度、候选人的真实简历原文片段、一审引用的依据与原始 0-100 分数，\n"
    "判断该分数是否被候选人的真实内容【充分支撑】。\n"
    "- 若支撑充分：justified=true，adjusted_score 与原始分数相同\n"
    "- 若支撑不足：justified=false，给出修正后的 adjusted_score（同 0-100 量表，\n"
    "  0=完全无相关内容，50=一般，100=杰出），附简短 reason\n"
    "保持保守：证据明确支持时才调整分数。只输出 JSON。"
)


async def _verify_score_llm(label: str, score: int, excerpt: str, user_id: int) -> int | None:
    """单个维度二评（DeepInterview _guarded 对照）：任何失败保原分（返回 None）。"""
    user_prompt = (
        f"评分维度：{label}\n"
        f"原始分数：{score} / 100\n\n"
        f"候选人简历原文片段：\n{excerpt[:4000]}\n\n"
        f"一审依据：该维度低于 {VERIFY_SCORE_THRESHOLD} 分（疑似低评或误评）"
    )
    try:
        raw = await asyncio.wait_for(
            with_retry(
                llm_generate,
                system=_VERIFY_SYSTEM,
                user=user_prompt,
                temperature=0.0,
                max_tokens=120,
                user_id=user_id,
                fallback='{"justified": true, "adjusted_score": 0, "reason": ""}',
                max_retries=1,
            ),
            timeout=VERIFY_TIMEOUT,
        )
        data = json.loads(raw.strip())
        if data.get("justified") is True:
            return None  # 分数站得住 → 保原分
        adjusted = int(data.get("adjusted_score", score))
        return max(0, min(100, adjusted))  # 夹紧（_clamp_score 对照）
    except Exception as e:
        logger.warning("评分二评失败（保原分）: %s: %s", label, e)
        return None


async def verify_scores(
    scores: ScoreDetail,
    parsed_text: str,
    user_id: int,
    evidence_text: str | None = None,
) -> ScoreDetail:
    """对抗二评（DeepInterview verifier.py 移植）：只审低分维度，grounded 原文，失败保原分。

    - 仅 `JUDGE_ENABLED` 时启用（对齐 Settings.enable_score_verifier 默认关）
    - 只审低于 VERIFY_SCORE_THRESHOLD 的维度（对齐 _VERIFY_LEVELS）
    - grounded 在简历原文（对齐"不拿一审自己的摘要评一审"防循环论证）
    - evidence_text：可选，Phase 2.5/P3 证据锚定的多段原文引用；传入时二评
      只 grounded 在证据片段（多段引用），缺省时退回全文 parsed_text 兜底
    - band 由 ScoreDetail model_validator 从最终分数重派生（分数↔档位同源）
    """
    if not settings.JUDGE_ENABLED or not parsed_text:
        return scores

    # P3: 优先用证据锚定片段（多段引用），否则退回全文
    excerpt_source = evidence_text or parsed_text

    low_dims: dict[str, int] = {}
    if scores.ats_match < VERIFY_SCORE_THRESHOLD:
        low_dims["ATS 匹配"] = scores.ats_match
    if scores.keyword_coverage < VERIFY_SCORE_THRESHOLD:
        low_dims["关键词覆盖"] = scores.keyword_coverage
    if scores.skill_density < VERIFY_SCORE_THRESHOLD:
        low_dims["技能密度"] = scores.skill_density
    if scores.overall < VERIFY_SCORE_THRESHOLD:
        low_dims["综合评价"] = scores.overall
    if not low_dims:
        return scores

    # 并发二评（独立维度互不依赖）
    import asyncio as _asyncio

    tasks = {
        label: _verify_score_llm(label, score, excerpt_source, user_id)
        for label, score in low_dims.items()
    }
    results = await _asyncio.gather(*tasks.values())

    adjusted: dict[str, int] = {}
    for label, value in zip(tasks.keys(), results):
        if value is not None:
            adjusted[label] = value
    if not adjusted:
        return scores

    logger.info("评分二评调整: %s", adjusted)
    return ScoreDetail(
        ats_match=adjusted.get("ATS 匹配", scores.ats_match),
        keyword_coverage=adjusted.get("关键词覆盖", scores.keyword_coverage),
        skill_density=adjusted.get("技能密度", scores.skill_density),
        overall=adjusted.get("综合评价", scores.overall),
    )


_ANALYSIS_PROMPTS: dict[str, str] = {
    "summary": (
        "请对以下简历内容进行全面总结，包括：\n"
        "1. 个人基本信息（姓名、联系方式）\n"
        "2. 教育背景\n"
        "3. 工作/实习经历概览\n"
        "4. 核心技能\n"
        "5. 整体评价\n"
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
        "每段经历结束后，请标注支撑该段经历的简历原文段落字符区间 "
        "refer_index_range（格式：refer_index_range: [起始, 结束]，如 "
        "refer_index_range: [120, 260]，起始/结束为简历内容中的字符位置，"
        "尽量覆盖包含公司名、职位和成就关键词的最小段落）。\n"
        "如果简历中没有工作经历，请说明。"
    ),
    "score": (
        "你是一个专业的简历评分专家。请从以下四个维度对简历进行量化评分：\n\n"
        "1. **ATS 匹配率**：简历结构是否清晰、关键词是否丰富、"
        "格式是否 ATS（Applicant Tracking System）友好\n"
        "2. **关键词覆盖率**：技术关键词、行业术语的覆盖广度\n"
        "3. **技能密度**：技能的深度和广度，是否有跨领域技能\n"
        "4. **综合评价**：综合以上维度的加权评分\n\n"
        "请给出支撑各维度评分的简历原文字符区间 refer_index_range（如 "
        "[120, 260]，对应简历内容的字符位置，指向包含相关关键词或句子的"
        "最小原文段落），并遵循证据锚定原则：每个分数必须能被该区间内的"
        "原文片段直接支撑，禁止编造简历中不存在的内容。\n"
        "推荐直接输出 JSON：{\"ats_match\": 分数, \"keyword_coverage\": 分数, "
        "\"skill_density\": 分数, \"overall\": 分数, "
        "\"refer_index_range\": [起始, 结束]}（overall 与 refer_index_range "
        "指向综合评价的核心证据段落）。\n\n"
        "请严格按以下格式输出：\n\n"
        "## 综合评分\n\n"
    ),
}


def _parse_scores(analysis: str) -> ScoreDetail | None:
    r"""从 LLM 返回的评分文本中提取量化分数。

    A3 评分契约升级（Magic-Resume JSON 契约对照）：JSON-first——
    LLM 输出完整 JSON 对象时直接过 ScoreDetail.model_validate（0-100 边界 +
    band 同源派生落在类型上）；非 JSON 输出回退到原有 4 级正则：
    1. Markdown 表格（最常见）
    2. JSON 键值（正则版）
    3. 键值对 / 分节标题（中英文标签：XX/100、XX分、score: XX、得分: XX，标签与数字可跨行）
    4. 裸数字序列（无标签，按出现顺序取前 4 个）

    非法分数（>100，如年份/ID）会被过滤，导致有效分数不足 4 个时返回 None。
    """
    if not analysis:
        return None

    # 0. JSON-first（Magic-Resume fit-report JSON 契约对照）：完整对象 → 契约校验直接返回
    try:
        data = json.loads(analysis.strip())
        if isinstance(data, dict) and all(
            k in data for k in ("ats_match", "keyword_coverage", "skill_density", "overall")
        ):
            return ScoreDetail.model_validate(data)  # 越界/缺键 → ValidationError → 正则降级
    except (json.JSONDecodeError, ValueError, ValidationError):
        pass  # 非 JSON 或契约不通过 → 走正则降级

    all_scores: list[int] = []

    # 1. 尝试从 Markdown 表格中提取
    table_pattern = re.compile(r"\|\s*(?:ATS|关键词|技能密度|综合|评价)\s*\|\s*(\d+)\s*\|")
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
            tail = analysis[m.end() : m.end() + 80]
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

    # 契约收口（Magic-Resume zod min/max 对照）：越界分数不落库
    try:
        return ScoreDetail(
            ats_match=valid_scores[0],
            keyword_coverage=valid_scores[1],
            skill_density=valid_scores[2],
            overall=valid_scores[3],
        )
    except ValidationError:
        return None


# ── Phase 2.5 / P3: 索引文本证据锚定（杜绝编造）────────────────
# 分析/评分 prompt 要求 LLM 输出 refer_index_range（parsed_text 字符区间），
# 后处理切片还原原文随结果返回 evidence_quote，作为结论的可溯源证据。

# 单个证据引用的最大字符数（防超大切片撑爆二评 prompt）
_EVIDENCE_QUOTE_MAX_CHARS = 800

_REFER_RANGE_RE = re.compile(
    # 形式 1: refer_index_range: [120, 260] / [120，260] / [120,260]
    r"refer[_\-]?index[_\-]?range\s*[:=：]?\s*"
    r"[\[（(]\s*(\d+)\s*[,，]\s*(\d+)\s*[\]）)]"
    r"|"
    # 形式 2: refer_index_range: 120-260 / 120~260
    r"refer[_\-]?index[_\-]?range\s*[:=：]?\s*"
    r"(\d+)\s*[-~]\s*(\d+)",
    re.IGNORECASE,
)


def _extract_evidence_ranges(analysis: str, parsed_text: str) -> list[dict]:
    """从 LLM 输出提取 refer_index_range，切片还原原文证据段落。

    Args:
        analysis: LLM 原始输出（JSON 或 markdown）
        parsed_text: 简历全文（切片基准）

    Returns:
        [{"start": int, "end": int, "quote": str}, ...]
        quote = parsed_text[start:end]（去首尾空白，限长）。
        区间越界自动夹紧、过短(<4)跳过、重复区间去重。无有效区间返回 []。
    """
    if not analysis or not parsed_text:
        return []
    total = len(parsed_text)
    out: list[dict] = []
    seen: set[tuple[int, int]] = set()
    for m in _REFER_RANGE_RE.finditer(analysis):
        if m.group(1) is not None:
            start, end = int(m.group(1)), int(m.group(2))
        else:
            start, end = int(m.group(3)), int(m.group(4))
        if start > end:
            start, end = end, start
        start = max(0, min(start, total))
        end = max(start, min(end, total))
        if end - start < 4:
            continue
        key = (start, end)
        if key in seen:
            continue
        seen.add(key)
        quote = parsed_text[start:end].strip()
        if not quote:
            continue
        out.append(
            {"start": start, "end": end, "quote": quote[:_EVIDENCE_QUOTE_MAX_CHARS]}
        )
    return out


def _evidence_quote(evidence_ranges: list[dict]) -> str | None:
    """多段证据拼接为引用文本（--- 分隔），供 verify_scores 二评 grounded。"""
    quotes = [r["quote"] for r in evidence_ranges if r.get("quote")]
    if not quotes:
        return None
    return "\n---\n".join(quotes)


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
        # P3 证据锚定：旧缓存无 evidence 字段 → None，新缓存原样带出
        return {
            "resume_id": resume_id,
            "analysis_type": analysis_type,
            "analysis": cached.get("analysis", ""),
            "scores": cached.get("scores"),
            "evidence": cached.get("evidence"),
            "evidence_quote": cached.get("evidence_quote"),
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

        async def _call() -> "object":
            return await client.chat.completions.create(
                model=settings.CHAT_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.0,
                # 结构化分析任务：显式关闭思考模式（模型默认 high effort 思考，
                # 纯格式化输出无需思考，提速降 token）
                extra_body={"thinking": {"type": "enabled" if settings.THINKING_ENABLED else "disabled"}},
                **({"reasoning_effort": settings.THINKING_EFFORT} if settings.THINKING_ENABLED else {}),
            )

        # 超时护栏（DeepInterview _guarded 对照）：LLM 挂起时返回明确错误而非无限等待
        response = await asyncio.wait_for(_call(), timeout=settings.ANALYZE_LLM_TIMEOUT)
        analysis = (response.choices[0].message.content or "").strip()
        usage_info = {}
        if hasattr(response, "usage") and response.usage:
            pt = getattr(response.usage, "prompt_tokens", 0) or 0
            ct = getattr(response.usage, "completion_tokens", 0) or 0
            usage_info = {"total_tokens": pt + ct, "prompt_tokens": pt, "completion_tokens": ct}
            # 统一记账
            await record_llm_usage(
                user_id,
                pt,
                ct,
                model=settings.CHAT_MODEL,
                scenario=f"analysis:{analysis_type}",
            )
            logger.info(
                "分析 token: type=%s, prompt=%d, completion=%d, total=%d",
                analysis_type,
                pt,
                ct,
                pt + ct,
            )
        else:
            logger.info(
                "分析无 usage 返回: type=%s, hasattr=%s", analysis_type, hasattr(response, "usage")
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
        "usage": usage_info,
    }

    # Phase 2.5/P3: 证据锚定——从 LLM 输出提取 refer_index_range，切片还原原文
    # 随结果返回 evidence（区间+原文引用）与 evidence_quote（多段拼接引用）。
    # 无有效区间时 evidence=[] / evidence_quote=None，向后兼容旧 LLM 输出。
    evidence_ranges = _extract_evidence_ranges(analysis, parsed_text)
    result["evidence"] = evidence_ranges
    result["evidence_quote"] = _evidence_quote(evidence_ranges)

    # score 类型：解析量化分数 → 对抗二评（DeepInterview verifier 移植，仅低分维度 + JUDGE_ENABLED）
    if analysis_type == "score":
        scores = _parse_scores(analysis)
        if scores is not None:
            verified = await verify_scores(
                scores,
                parsed_text,
                user_id,
                evidence_text=result.get("evidence_quote"),
            )
            result["scores"] = verified.model_dump()

    return result


# ── E3: 多角色 LLM 评分（peer/lead/HRBP）─────────────────────
# 三角色同 0-100 量表，JSON 输出；聚合权重来自 rubric.json（I2 可配置）。
# 与现有 score/evidence 结构兼容（新增 roles 字段，不破坏旧消费方）。

_ROLES_SYSTEM = (
    "你是一位资深招聘评估委员会。请分别从三个视角对候选人简历打分（每个 0-100）：\n"
    "1. peer（同级别评估）：与候选人同级别的工程师/同事视角——技术深度、协作与执行力的同级感知\n"
    "2. lead（团队负责人评估）：团队负责人/主管视角——产出影响力、领导力、成长潜力与晋升依据\n"
    "3. hrbp（HRBP 评估）：HR 视角——文化契合、稳定性、软技能与沟通表达\n\n"
    "严格输出 JSON 对象（不要 Markdown，不要 ```json 包裹）：\n"
    '{"peer": {"score": <0-100 整数>, "summary": "<一句话理由>"},\n'
    ' "lead": {"score": <0-100 整数>, "summary": "<一句话理由>"},\n'
    ' "hrbp": {"score": <0-100 整数>, "summary": "<一句话理由>"}}\n'
    "打分必须 grounded 在简历真实内容，禁止编造简历中不存在的经历/成就。"
)


def _parse_roles(analysis: str) -> dict | None:
    """从 LLM JSON 输出解析三角色分数。"""
    if not analysis:
        return None
    try:
        data = json.loads(analysis.strip())
    except (json.JSONDecodeError, ValueError):
        # 抗截断：取首个 {..} 区间
        start, end = analysis.find("{"), analysis.rfind("}")
        if start == -1 or end <= start:
            return None
        try:
            data = json.loads(analysis[start : end + 1])
        except json.JSONDecodeError:
            return None
    if not isinstance(data, dict):
        return None

    roles: dict[str, dict] = {}
    for role in ("peer", "lead", "hrbp"):
        item = data.get(role)
        if not isinstance(item, dict):
            return None
        score = item.get("score")
        if not isinstance(score, (int, float)):
            return None
        roles[role] = {
            "score": max(0, min(100, int(score))),
            "summary": str(item.get("summary", "")).strip()[:300],
        }
    return roles


async def analyze_resume_roles(
    db: AsyncSession,
    user_id: int,
    resume_id: int,
    target_position: str | None = None,
) -> dict:
    """多角色评分：peer/lead/HRBP 各打 0-100 + 加权聚合（rubric 权重）。

    Returns:
        {
            "resume_id", "analysis_type": "roles",
            "analysis": 三角色 Markdown 摘要,
            "roles": {peer: {score, summary}, ...},
            "aggregate": {"score", "band", "weights"},
            "target_position",
            "evidence": [...], "evidence_quote": ...   # 证据锚定（Phase 2.5 对齐）
        }

    Raises:
        HTTPException: 404 简历不存在 / 409 未就绪 / 422 内容为空 / 500 LLM 失败
    """
    from services.rubric import get_role_weights, role_aggregate

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

    role_cfg = get_role_weights()
    role_descs = "；".join(
        f"{role}（{cfg.get('label', role)}）：{cfg.get('description', '')}"
        for role, cfg in role_cfg.items()
    )
    position_hint = f"\n目标岗位：{target_position}" if target_position else ""

    system = _ROLES_SYSTEM + f"\n\n三个视角的评估权重说明（供参考）：\n{role_descs}"
    user_prompt = (
        f"简历内容：\n\n{parsed_text}\n\n"
        f"{position_hint}\n请按 JSON 契约输出三角色评分。"
    )

    try:
        client = get_chat_client()

        async def _call() -> "object":
            return await client.chat.completions.create(
                model=settings.CHAT_MODEL,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.0,
                # 结构化评分任务：显式关闭思考模式（同上，纯 JSON 契约输出）
                extra_body={"thinking": {"type": "enabled" if settings.THINKING_ENABLED else "disabled"}},
                **({"reasoning_effort": settings.THINKING_EFFORT} if settings.THINKING_ENABLED else {}),
            )

        response = await asyncio.wait_for(_call(), timeout=settings.ANALYZE_LLM_TIMEOUT)
        analysis = (response.choices[0].message.content or "").strip()
        usage_info = {}
        if hasattr(response, "usage") and response.usage:
            pt = getattr(response.usage, "prompt_tokens", 0) or 0
            ct = getattr(response.usage, "completion_tokens", 0) or 0
            usage_info = {"total_tokens": pt + ct, "prompt_tokens": pt, "completion_tokens": ct}
            await record_llm_usage(
                user_id,
                pt,
                ct,
                model=settings.CHAT_MODEL,
                scenario="analysis:roles",
            )
    except Exception as e:
        logger.exception("analyze_resume_roles failed for resume %d", resume_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="多角色评分失败，请稍后重试",
        )

    roles = _parse_roles(analysis)
    if roles is None:
        # 解析失败：给确定性兜底（分数不可用 → 明确提示，不静默给 0）
        return {
            "resume_id": resume_id,
            "analysis_type": "roles",
            "analysis": "多角色评分失败：AI 输出无法解析，请重试。",
            "roles": {},
            "aggregate": {"score": 0, "band": "needsWork", "weights": {}},
            "target_position": target_position,
            "usage": usage_info,
            "evidence": [],
            "evidence_quote": None,
        }

    aggregate_score = role_aggregate(roles)
    from schemas.resume import derive_band

    # 证据锚定（Phase 2.5 对齐）：从输出提取 refer_index_range 还原原文
    evidence_ranges = _extract_evidence_ranges(analysis, parsed_text)

    # Markdown 摘要（含角色权重标签）
    lines = ["## 三角色评分", ""]
    for role, cfg in role_cfg.items():
        item = roles.get(role, {})
        lines.append(
            f"- **{cfg.get('label', role)}**：{item.get('score', '-')} / 100"
            + (f"（{item.get('summary', '')}）" if item.get("summary") else "")
        )
    lines.append("")
    lines.append(f"**加权总分：{aggregate_score} / 100（{derive_band(aggregate_score)}）**")

    return {
        "resume_id": resume_id,
        "analysis_type": "roles",
        "analysis": "\n".join(lines),
        "roles": roles,
        "aggregate": {
            "score": aggregate_score,
            "band": derive_band(aggregate_score),
            "weights": {k: v.get("weight", 0) for k, v in role_cfg.items()},
        },
        "target_position": target_position,
        "usage": usage_info,
        "evidence": evidence_ranges,
        "evidence_quote": _evidence_quote(evidence_ranges),
    }


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
