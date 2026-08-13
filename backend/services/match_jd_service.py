"""JD-Resume 匹配分析服务。

将简历内容与 JD（Job Description）文本进行 LLM 对比分析，
返回匹配分数、匹配点、差距分析和改进建议。

A3 评分契约升级（Magic-Resume fit-report.ts 对照）：JSON-first 结构化输出
（score/matched/missing/gaps/reason），解析失败降级为原 markdown 分析。
"""

import json
import logging
import re

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
    "## 匹配分数\n\n\n"
    "## 匹配点\n（列出简历中与 JD 要求匹配的技能、经验和经历）\n\n"
    "## 差距分析\n（列出 JD 要求但简历中缺失或不足的技能/经验）\n\n"
    "## 改进建议\n（针对差距给出具体可执行的改进建议）"
)

# Magic-Resume FitReport 契约对照：结构化 JSON 输出（JSON-first）
# E3 升级：四维 JD fit（technical/experience/behavioral/career），overall 由
# rubric 权重代码计算（维度与分数绝不由 LLM 同时给，避免不一致），兼容旧 score 字段。
_STRUCTURED_SYSTEM = (
    "你是一个专业的招聘分析师。将简历与 JD 对比分析。\n"
    "严格输出 JSON 对象（不要 Markdown，不要 ```json 包裹）：\n"
    '{"dims": {"technical": <0-100 整数, 技术栈/工具匹配>,\n'
    '           "experience": <0-100 整数, 年限/项目复杂度匹配>,\n'
    '           "behavioral": <0-100 整数, 软技能/协作/主动性>,\n'
    '           "career": <0-100 整数, 职业方向/行业背景契合>},\n'
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


_FIT_DIMENSIONS = ("technical", "experience", "behavioral", "career")

_KEYWORD_ALIASES: tuple[set[str], ...] = (
    {"kubernetes", "k8s"},
    {"continuous integration", "ci/cd", "github actions"},
    {"large language model", "llm", "大模型"},
)


def _resume_contains_keyword(resume_text: str, keyword: str) -> bool:
    """Deterministically reject an LLM 'missing' claim contradicted by the CV."""
    haystack = resume_text.casefold()
    needle = str(keyword or "").strip().casefold()
    if not needle:
        return False
    if needle in haystack:
        return True
    for aliases in _KEYWORD_ALIASES:
        if any(alias in needle for alias in aliases):
            return any(alias in haystack for alias in aliases)
    # Phrases such as "Kubernetes 经验" should still match an explicit skill.
    technical_tokens = re.findall(r"[a-z][a-z0-9.+#/-]{1,}", needle)
    return bool(technical_tokens) and all(token in haystack for token in technical_tokens)


def _normalize_matched_evidence(resume_text: str, item: str) -> str:
    """Keep exact evidence verbatim; downgrade loose keyword co-occurrence.

    An LLM may turn a skill-list keyword into an unsupported depth claim such as
    “Kubernetes deployment experience”.  When the complete phrase cannot be
    located, expose only the technical keywords and mark depth as unverified.
    """
    raw = str(item or "").strip()
    compact_resume = re.sub(r"\s+", "", resume_text).casefold()
    compact_item = re.sub(r"\s+", "", raw).casefold()
    if compact_item and compact_item in compact_resume:
        return raw

    original_tokens = re.findall(r"[A-Za-z][A-Za-z0-9.+#/-]{1,}", raw)
    present_tokens = []
    for token in original_tokens:
        if token.casefold() in resume_text.casefold() and token.casefold() not in {
            existing.casefold() for existing in present_tokens
        }:
            present_tokens.append(token)
    if present_tokens:
        return f"{' / '.join(present_tokens)}（关键词出现，关联实践深度待核对）"
    return raw


def _clamp_score(value) -> int:
    try:
        return max(0, min(100, int(value)))
    except (TypeError, ValueError):
        return 0


def _parse_fit_dims(data: dict) -> dict[str, int]:
    """解析四维分数。缺维 → 该维 0（整体不参与）。"""
    dims_raw = data.get("dims")
    dims: dict[str, int] = {}
    if isinstance(dims_raw, dict):
        for d in _FIT_DIMENSIONS:
            v = dims_raw.get(d)
            if isinstance(v, (int, float)):
                dims[d] = _clamp_score(v)
    return dims


async def _structured_match(user_prompt: str, user_id: int) -> dict | None:
    """结构化匹配（JSON-first）：失败返回 None → 调用方降级 markdown。

    E3 四维 JD fit：overall 由 rubric 权重加权计算（jd_fit_overall），
    维度分数与总分同源；旧 `score` 字段作为 LLM 未输出 dims 时的兜底。
    """
    from services.rubric import jd_fit_overall

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
        dims = _parse_fit_dims(data)
        if len(dims) == len(_FIT_DIMENSIONS):
            overall = jd_fit_overall(dims)  # 权重来自 rubric（I2 可编辑）
        else:
            # 旧契约兜底：直接读 score
            overall = _clamp_score(data.get("score", 0))
        return {
            "score": overall,
            "band": derive_band(overall),
            "dims": dims,
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
        # band 由分数派生，拒绝 LLM/缓存返回的旧字母档位，避免响应模型 500。
        structured["band"] = derive_band(_clamp_score(structured.get("score", 0)))
        # LLM 只负责抽取候选匹配项；最终“已匹配”必须能在简历原文中定位。
        # 这样不会把相近概念（例如 Reflexion 与 ReAct）直接当作同一项。
        validated_matched = [
            _normalize_matched_evidence(parsed_text, item)
            for item in structured["matched"]
            if _resume_contains_keyword(parsed_text, item)
        ]
        # 保持原顺序语义去重，避免 “Kubernetes” 与降级后的 Kubernetes 说明重复。
        unique_matched: list[str] = []
        seen_matched: set[str] = set()
        for item in validated_matched:
            key = item.split("（", 1)[0].strip().casefold()
            if key in seen_matched:
                continue
            seen_matched.add(key)
            unique_matched.append(item)
        structured["matched"] = unique_matched
        contradicted_missing = [
            item for item in structured["missing"]
            if _resume_contains_keyword(parsed_text, item)
        ]
        if contradicted_missing:
            structured["missing"] = [
                item for item in structured["missing"]
                if item not in contradicted_missing
            ]
            # A missing claim may be contradicted only by a skill-list keyword. Do not
            # promote the LLM's original depth claim (for example “Kubernetes 部署经验”)
            # back into matched after the evidence-normalization pass above.
            existing = {
                item.split("（", 1)[0].strip().casefold()
                for item in structured["matched"]
            }
            for raw_item in contradicted_missing:
                normalized = _normalize_matched_evidence(parsed_text, raw_item)
                key = normalized.split("（", 1)[0].strip().casefold()
                if key in existing:
                    continue
                existing.add(key)
                structured["matched"].append(normalized)
            structured["gaps"] = [
                gap for gap in structured["gaps"]
                if not any(item.casefold() in gap.casefold() for item in contradicted_missing)
            ]
        reason = (
            f"文本匹配参考分 {structured['score']}/100；"
            f"简历原文可定位 {len(structured['matched'])} 项，"
            f"证据不足或缺失 {len(structured['missing'])} 项。"
            "该分数只反映当前文本覆盖，不代表 ATS 通过率或录用概率。"
        )
        return {
            "resume_id": resume_id,
            "analysis": reason,
            "scores": {"overall": structured["score"], "band": structured["band"]},
            "dims": structured["dims"],  # E3 四维 JD fit（technical/experience/behavioral/career）
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


# ═══════════════════════════════════════════════════════════
# I1: JD 6-block 评估报告（JobMcp report_format.md 对照）
# 角色摘要 / CV 匹配表 / 级别策略 / 薪酬市场 / 个性化计划 / 面试故事映射 /
# Block G 岗位可信度防坑。LLM JSON 生成 + 确定性模板兜底。
# ═══════════════════════════════════════════════════════════

_6BLOCK_SYSTEM = (
    "你是一位资深求职顾问。基于候选人简历与 JD 生成 6-block 求职评估报告。\n"
    "严格输出 JSON 对象（不要 Markdown，不要 ```json 包裹），结构如下：\n"
    "{\n"
    '  "role_summary": {"archetype": "岗位类型（如 Agentic/FDE/后端）", "domain": "领域", '
    '"function": "build/consult/manage/deploy", "seniority": "intern→principal", '
    '"remote": "full/hybrid/onsite", "team_size": "团队规模或省略", "tldr": "一句话总结"},\n'
    '  "cv_match": {"table": [{"jd_requirement": "JD 要求", "cv_evidence": "简历对应行/证据", '
    '"status": "matched|partial|missing"}], '
    '"gaps": [{"type": "hard_blocker|nice_to_have", "adjacent": "邻近经验", "mitigation": "求职信缓解话术"}]},\n'
    '  "level_strategy": {"jd_level": "JD 暗示的级别", "candidate_level": "候选人自然级别", '
    '"sell_senior_plan": "不撒谎地体现资深的话术与亮点", "downlevel_plan": "被降级时的应对（薪资合理则接受/6个月复审/晋升标准）"},\n'
    '  "comp_market": {"market_range": "市场薪酬区间", "base_hint": "锚定建议", '
    '"sources": ["薪资来源，如 Levels.fyi/看准/Boss"], "notes": "无数据时如实说明，不编造数字"},\n'
    '  "personalization_plan": {"cv_changes": [{"section": "简历板块", "current": "现状", '
    '"proposed": "建议改写", "why": "理由"}], "linkedin_changes": []},\n'
    '  "interview_stories": [{"jd_requirement": "JD 要求", "story_title": "故事标题", '
    '"s": "Situation", "t": "Task", "a": "Action", "r": "Result", "reflection": "反思"}]，\n'
    '  "job_credibility": {"tier": "high_confidence|proceed_with_caution|suspicious", '
    '"signals": [{"signal": "观察到的信号", "risk": "high|medium|low", "note": "解释"}], '
    '"conclusion": "结论"}\n'
    "}\n"
    "硬性要求：\n"
    "1. cv_match / interview_stories / personalization_plan 必须 grounded 在简历真实内容，"
    "不得编造简历中不存在的公司/项目/成就；\n"
    "2. comp_market 没有可靠数据时 notes 如实写『无市场数据』，绝不虚构薪资数字；\n"
    "3. job_credibility 是呈现观察而非指控——每个信号都有合理解释；观察发布时长（30天内佳/"
    "60天+需谨慎）、岗位要求内部矛盾（如初级头衔却要求 Staff 能力）、重复发布模式（90天内同一岗位发布 2 次以上）等；\n"
    "4. 面试故事 6-10 条，每条含 STAR 四要素 + 反思。"
)


def _fallback_6block() -> dict:
    """确定性模板兜底（LLM 失败时给出诚实的最小结构）。"""
    return {
        "role_summary": {
            "archetype": "（未能解析）",
            "domain": "（未能解析）",
            "function": "（未能解析）",
            "seniority": "（未能解析）",
            "remote": "（未能解析）",
            "team_size": "",
            "tldr": "LLM 生成失败，可重试。",
        },
        "cv_match": {"table": [], "gaps": []},
        "level_strategy": {
            "jd_level": "（未能解析）",
            "candidate_level": "（未能解析）",
            "sell_senior_plan": "",
            "downlevel_plan": "",
        },
        "comp_market": {
            "market_range": "（未能解析）",
            "base_hint": "",
            "sources": [],
            "notes": "LLM 生成失败，未获取市场数据。",
        },
        "personalization_plan": {"cv_changes": [], "linkedin_changes": []},
        "interview_stories": [],
        "job_credibility": {
            "tier": "proceed_with_caution",
            "signals": [],
            "conclusion": "LLM 生成失败，无法评估岗位可信度；请人工核对岗位来源与发布时效。",
        },
    }


def _normalize_6block(data: dict) -> dict:
    """结构兜底：缺失的 block 用空结构补齐，保证前端可渲染。"""
    fb = _fallback_6block()
    out: dict = {}
    for key, fallback_val in fb.items():
        val = data.get(key)
        if val is None:
            out[key] = fallback_val
        elif isinstance(val, dict):
            # 逐字段兜底
            merged = dict(fallback_val) if isinstance(fallback_val, dict) else {}
            for fk, fv in val.items():
                merged[fk] = fv
            out[key] = merged
        elif isinstance(val, list):
            out[key] = val if isinstance(fallback_val, list) else fallback_val
        else:
            out[key] = fallback_val
    return out


async def build_6_block_report(
    parsed_text: str,
    jd_text: str,
    fit: dict | None,
    user_id: int,
) -> dict:
    """生成 6-block 求职评估报告（LLM JSON + 确定性模板兜底）。

    Args:
        parsed_text: 简历全文
        jd_text: JD 原文
        fit: match_jd 的结构化匹配结果（scores/dims/matched/missing/gaps），用于注入
        user_id: LLM 用量记账

    Returns:
        6-block 报告 dict（role_summary/cv_match/level_strategy/comp_market/
        personalization_plan/interview_stories/job_credibility）
    """
    fit_hint = ""
    if fit:
        fit_hint = (
            f"\n\n已有匹配数据（参考，勿重复计算）：\n"
            f"- overall: {fit.get('scores', {}).get('overall')} "
            f"band: {fit.get('scores', {}).get('band')}\n"
            f"- dims: {fit.get('dims')}\n"
            f"- matched: {fit.get('matched_keywords', [])}\n"
            f"- missing: {fit.get('missing_keywords', [])}"
        )

    user_prompt = (
        f"候选人简历：\n{parsed_text[:6000]}\n\n"
        f"目标 JD：\n{jd_text[:5000]}"
        f"{fit_hint}\n\n请按 JSON 契约生成 6-block 求职评估报告。"
    )

    try:
        raw = await with_retry(
            llm_generate,
            _6BLOCK_SYSTEM,
            user_prompt,
            user_id=user_id,
            temperature=0.3,
            fallback="",
            max_retries=1,
        )
        data = _extract_json_object(raw)
        if not isinstance(data, dict):
            raise ValueError("6-block 报告非对象")
        return _normalize_6block(data)
    except Exception as e:
        logger.warning("6-block 报告生成失败（使用模板兜底）: %s", e)
        return _fallback_6block()


async def save_jd_report(
    db: AsyncSession,
    user_id: int,
    resume_id: int,
    jd_text: str,
    report: dict,
    overall: int,
    band: str,
) -> bool:
    """JD 6-block 报告落库（同 (user, resume, jd_hash) 幂等 upsert）。

    本函数自管事务（内部 commit/rollback）；调用方（JDMatchTool）使用独立 session。
    best-effort：失败只记日志，不阻断主流程。

    Args:
        db: DB session（事务由本函数管理）
        user_id / resume_id / jd_text: 归属与幂等键
        report: 6-block 报告 dict
        overall / band: 汇总匹配分

    Returns:
        True 落库成功；False 失败（不抛异常，不阻断主流程）
    """
    from models.jd_match_report import JdMatchReport

    try:
        h = jd_text_hash(jd_text)
        result = await db.execute(
            select(JdMatchReport).where(
                JdMatchReport.user_id == user_id,
                JdMatchReport.resume_id == resume_id,
                JdMatchReport.jd_text_hash == h,
            )
        )
        row = result.scalar_one_or_none()
        if row is None:
            row = JdMatchReport(
                user_id=user_id,
                resume_id=resume_id,
                jd_text_hash=h,
                jd_text=jd_text,
                report=report,
                overall=overall,
                band=band,
            )
            db.add(row)
        else:
            row.jd_text = jd_text
            row.report = report
            row.overall = overall
            row.band = band
        await db.commit()
        return True
    except Exception as e:
        logger.warning("save_jd_report 落库失败（忽略）: %s", e)
        try:
            await db.rollback()
        except Exception:
            pass
        return False


def jd_text_hash(jd_text: str) -> str:
    import hashlib

    return hashlib.sha256(jd_text.encode("utf-8")).hexdigest()
