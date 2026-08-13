"""面试复盘闭环服务（G 功能）。

面后记录 → 录入评分卡 → 派生薄弱点 → 复盘汇总（高频薄弱点 / 训练推荐 / 历史趋势）。
设计思路对照 DeepInterview：sessions 表一次写入可重复评分 + run_coach_plan
（weak_competencies → 学习模块，最弱优先）。不引第三方代码，翻译为现有
FastAPI + SQLAlchemy 风格；训练推荐用确定性模板（无 LLM 依赖）。
"""

import logging

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions import AppException
from models.interview_session import InterviewSession
from models.job_application import JobApplication
from services.memory.memory_store import save_memory

logger = logging.getLogger(__name__)

# 低分维度阈值：< 70 视为薄弱项（DeepInterview scoreband / 项目评分档位对照）
WEAK_SCORE_THRESHOLD = 70
# 训练模块默认预估分钟（DeepInterview coach _DEFAULT_EST_MIN = 25 对照）
_DEFAULT_EST_MIN = 25

# 常见薄弱点 → 训练模块确定性模板（title / rationale / est_min）
_MODULE_TEMPLATES: dict[str, dict] = {
    "算法": {
        "title": "算法专项刷题",
        "rationale": "算法维度失分，建议按标签专题刷题并总结解题套路，兼顾时间/空间复杂度与边界条件",
        "est_min": 40,
    },
    "算法与数据结构": {
        "title": "算法与数据结构专项刷题",
        "rationale": "算法与数据结构维度失分，建议按标签专题刷题并总结解题套路，兼顾复杂度与边界条件",
        "est_min": 40,
    },
    "数据结构": {
        "title": "数据结构查漏补缺",
        "rationale": "数据结构基础不牢，建议复习常用结构（数组/链表/树/哈希/堆）并配套练习",
        "est_min": 30,
    },
    "系统设计": {
        "title": "系统设计方法论训练",
        "rationale": "系统设计维度偏弱，建议按「需求澄清 → 容量估算 → 模块划分 → 扩展性」框架练习",
        "est_min": 45,
    },
    "项目深挖": {
        "title": "项目经历 STAR 复盘",
        "rationale": "项目讲述缺乏量化与深度，建议用 STAR 法重写项目故事并预演深度追问",
        "est_min": 30,
    },
    "数据库": {
        "title": "数据库原理与优化",
        "rationale": "数据库问题回答不透彻，建议复习索引/事务/锁机制并练习 SQL 优化",
        "est_min": 35,
    },
    "操作系统": {
        "title": "操作系统核心概念梳理",
        "rationale": "操作系统知识点有漏洞，建议梳理进程/线程/内存/IO 四大块并串讲高频题",
        "est_min": 35,
    },
    "计算机网络": {
        "title": "计算机网络分层回顾",
        "rationale": "网络协议理解不深，建议按 TCP/IP 分层逐层复习重点协议与常见面试题",
        "est_min": 30,
    },
    "沟通表达": {
        "title": "表达结构化训练",
        "rationale": "回答缺乏结构，建议练习「结论先行 → 分点展开」的表达框架并录音回放",
        "est_min": 25,
    },
    "行为面试": {
        "title": "行为面试素材打磨",
        "rationale": "行为面试答得空洞，建议准备 8-10 个 STAR 案例并反复演练",
        "est_min": 25,
    },
}


def derive_weak_competencies(scorecard) -> list[str]:
    """从 scorecard 提取低分维度（<70）的维度名，纯函数。

    scorecard 形状（DeepInterview ScoreCard 对照）：
        {
          "overall_score": 72,
          "competency_scores": [{"competency": "算法", "score": 60}, ...],
          "weak_competencies": [...],  # 可选：显式消费契约，优先采用
          "notes": "..."
        }

    - 显式 weak_competencies（学习闭环消费契约）非空时优先采用；
    - 否则从 competency_scores 提取 score < 70 的维度名。
    """
    if not scorecard or not isinstance(scorecard, dict):
        return []

    explicit = scorecard.get("weak_competencies")
    if isinstance(explicit, list) and explicit:
        return [str(c) for c in explicit if isinstance(c, str) and c.strip()]

    weak: list[str] = []
    for item in scorecard.get("competency_scores") or []:
        if not isinstance(item, dict):
            continue
        name = item.get("competency") or item.get("name")
        score = item.get("score")
        if name and isinstance(score, (int, float)) and score < WEAK_SCORE_THRESHOLD:
            weak.append(str(name))
    return weak


def _competency_score(scorecard: dict, competency: str) -> int:
    """取某 competency 的分数（排序用）；缺失时返回阈值分（视为临界弱项）。"""
    for item in scorecard.get("competency_scores") or []:
        if not isinstance(item, dict):
            continue
        name = item.get("competency") or item.get("name")
        if name == competency and isinstance(item.get("score"), (int, float)):
            return int(item["score"])
    return WEAK_SCORE_THRESHOLD


def _build_module(index: int, competency: str) -> dict:
    """为一个薄弱点生成训练模块（确定性模板，最弱优先由调用方排序保证）。"""
    tpl = _MODULE_TEMPLATES.get(competency, {})
    return {
        "id": f"m{index}",
        "competency": competency,
        "title": tpl.get("title", f"强化 {competency}"),
        "rationale": tpl.get(
            "rationale",
            f"{competency} 在最近面试中被评估为薄弱项，建议针对性复盘和练习",
        ),
        "est_min": tpl.get("est_min", _DEFAULT_EST_MIN),
    }


async def create_interview(
    db: AsyncSession,
    user_id: int,
    *,
    company: str,
    position: str,
    resume_id: int | None = None,
    job_application_id: int | None = None,
    jd_text: str | None = None,
    questions: list | None = None,
    answers: list | None = None,
    notes: str | None = None,
    scorecard: dict | None = None,
) -> InterviewSession:
    """落库一次面试记录。传了 scorecard 即视为已复盘（status=reviewed）。

    job_application_id：关联投递记录（可选，打通投递看板某面次）；存在但非本人 → 404（防枚举）。
    jd_text 未传且关联投递有 JD → 自动取投递 jd_text（少粘一次）。
    """
    if job_application_id is not None:
        app = (
            await db.execute(
                select(JobApplication).where(
                    JobApplication.id == job_application_id,
                    JobApplication.user_id == user_id,
                )
            )
        ).scalar_one_or_none()
        if app is None:
            raise AppException(status_code=404, detail="关联的投递记录不存在或无权访问")
        if jd_text is None and app.jd_text:
            jd_text = app.jd_text

    session = InterviewSession(
        user_id=user_id,
        company=company,
        position=position,
        resume_id=resume_id,
        job_application_id=job_application_id,
        jd_text=jd_text,
        questions=questions,
        answers=answers,
        notes=notes,
        scorecard=scorecard,
        status="reviewed" if scorecard else "recorded",
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session


async def get_interviews(
    db: AsyncSession, user_id: int, page: int, limit: int
) -> tuple[list[InterviewSession], int]:
    """分页列表（按 created_at 倒序）。返回 (items, total)。"""
    total = (
        await db.execute(
            select(func.count())
            .select_from(InterviewSession)
            .where(InterviewSession.user_id == user_id)
        )
    ).scalar_one()

    result = await db.execute(
        select(InterviewSession)
        .where(InterviewSession.user_id == user_id)
        .order_by(InterviewSession.created_at.desc())
        .offset((page - 1) * limit)
        .limit(limit)
    )
    return result.scalars().all(), total


async def get_interview(db: AsyncSession, user_id: int, interview_id: int) -> InterviewSession:
    """查单条面试详情；不存在或非本人 → 404（防枚举）。"""
    result = await db.execute(
        select(InterviewSession).where(
            InterviewSession.id == interview_id,
            InterviewSession.user_id == user_id,
        )
    )
    session = result.scalar_one_or_none()
    if session is None:
        raise AppException(status_code=404, detail="面试记录不存在或无权访问")
    return session


async def delete_interview(db: AsyncSession, user_id: int, interview_id: int) -> None:
    """删面试记录；不存在或非本人 → 404。"""
    session = await get_interview(db, user_id, interview_id)
    await db.delete(session)
    await db.commit()


async def update_scorecard(
    db: AsyncSession,
    user_id: int,
    interview_id: int,
    scorecard: dict,
    notes: str | None = None,
) -> InterviewSession:
    """录入/更新评分卡（整块 JSON）+ status=reviewed；不存在或非本人 → 404。"""
    session = await get_interview(db, user_id, interview_id)
    session.scorecard = scorecard
    if notes is not None:
        session.notes = notes
    session.status = "reviewed"
    await db.commit()
    await db.refresh(session)

    # B 回流：复盘结果沉淀到 L4 长期记忆（面试弱项 → 后续面试教练/问答可召回）
    try:
        weak = derive_weak_competencies(scorecard)
        if weak:
            await save_memory(
                user_id=user_id,
                snippet=f"面试复盘（{session.company or '未知公司'} {session.position or '未知岗位'}）："
                f"薄弱项 {', '.join(weak)}",
                memory_type="semantic",
                importance=0.7,
            )
    except Exception:
        # 记忆沉淀是增强信息，失败不阻断评分卡保存
        logger.warning("面试复盘结果沉淀 L4 记忆失败 interview_id=%s", interview_id, exc_info=True)

    return session


async def build_review_summary(db: AsyncSession, user_id: int) -> dict:
    """复盘汇总：高频薄弱点 + 训练推荐（最弱优先）+ 历史面试趋势。

 run_coach_plan：weak_competencies → 学习模块，最弱优先。
    只读 created_at + scorecard 两列（避免拉取 transcript 大字段）。
    """
    result = await db.execute(
        select(InterviewSession.created_at, InterviewSession.scorecard)
        .where(InterviewSession.user_id == user_id)
        .order_by(InterviewSession.created_at.asc())
    )
    rows = result.all()

    # ── 趋势：全部面试按天聚合条数（含未评分）──
    trend: dict[str, int] = {}
    for row in rows:
        day = row.created_at.strftime("%Y-%m-%d") if row.created_at else ""
        if day:
            trend[day] = trend.get(day, 0) + 1

    # ── 薄弱点聚合：只统计有评分卡的面试 ──
    comp_counts: dict[str, int] = {}  # competency → 出现次数
    comp_worst: dict[str, int] = {}   # competency → 最差分（训练排序用）
    for row in rows:
        if not row.scorecard:
            continue
        for comp in derive_weak_competencies(row.scorecard):
            comp_counts[comp] = comp_counts.get(comp, 0) + 1
            score = _competency_score(row.scorecard, comp)
            if comp not in comp_worst or score < comp_worst[comp]:
                comp_worst[comp] = score

    # 高频薄弱点：按出现次数降序，同次数按最差分升序
    frequent = sorted(
        ({"competency": c, "count": n} for c, n in comp_counts.items()),
        key=lambda item: (-item["count"], comp_worst[item["competency"]]),
    )

    # ── 训练推荐：最弱优先（最差分升序），一个薄弱点一个模块 ──
    ordered_comps = sorted(comp_worst, key=lambda c: comp_worst[c])
    modules = [_build_module(i, comp) for i, comp in enumerate(ordered_comps, start=1)]
    total_min = sum(m["est_min"] for m in modules)
    if modules:
        summary = f"{len(modules)} 个薄弱项，预计共 {total_min} 分钟可完成针对性训练。"
    else:
        summary = "最近没有明显薄弱项——保持状态，继续多轮模拟面试巩固。"

    return {
        "frequent_weaknesses": frequent,
        "training_plan": {
            "modules": modules,
            "summary": summary,
            "total_min": total_min,
        },
        "trend": [{"period": day, "count": n} for day, n in sorted(trend.items())],
    }
