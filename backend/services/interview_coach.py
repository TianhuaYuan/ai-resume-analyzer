"""多轮模拟面试状态机（H1-H3，阶段 5，DeepInterview prep/live/post 对照）。

三段式设计（与 DeepInterview prep/live/post 对齐，但翻译为现有 FastAPI +
SQLAlchemy 风格，不引第三方代码）：

- H1 prep   生成题单 QuestionPlan（LLM 生成 + 确定性模板兜底）。
- H2 live   纯函数状态机 current_question / advance / is_complete：一问一答推进，
            每问只出一题（含追问），答完再出下一题。
- H3 post   面试完成自动逐题评分 → ScoreCard（coverage_pct / model_answers /
            weak_competencies），写入 InterviewSession（公司=模拟面试）流入复盘闭环。

与 Agent loop 的多轮交互方式：
    InterviewCoachTool 每次调用都创建一个全新工具实例（loop.py _execute_tool_call
    内 tool_class(db=db, user_id=user_id)），因此「多轮状态」必须落库持久化——
    状态存 interview_simulations 表（plan/cursor/followup_index/answers），
    按 (user_id, resume_id) 解析当前进行中的面试；每次工具调用推进一问。

状态机约定（H2 纯函数）：
    - cursor         当前题目下标（0-based）
    - followup_index 当前题目内「正在追问的追问下标」；-1 = 当前是主问题
    - current_question(sim)  → 当前题目 dict（cursor 越界返回 None）
    - current_prompt(sim)    → 当前要展示的文本（追问优先于主问题）
    - advance(sim)           → 追问未问完则推进追问；否则 cursor+1 并重置追问
    - is_complete(sim)       → cursor >= len(plan)
"""

import json
import logging
import re
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.interview_simulation import InterviewSimulation

logger = logging.getLogger(__name__)

# ── 常量 ──────────────────────────────────────────────────────
MAX_PLAN_QUESTIONS = 8
MIN_PLAN_QUESTIONS = 6
COMPANY_LABEL = "模拟面试"  # 写入 InterviewSession 的公司名（复盘闭环入口）

# 评分阈值对齐 interview_service.WEAK_SCORE_THRESHOLD（<70 视为薄弱项）
WEAK_SCORE_THRESHOLD = 70

# 确定性兜底题单（模板生成，LLM 失败时使用）
_TEMPLATE_SECTIONS: list[dict] = [
    {
        "section": "自我介绍",
        "difficulty": 1,
        "target_competency": "沟通表达",
        "question": "请先做个自我介绍，并说明你为什么申请{position}这个岗位。",
        "followups": ["你觉得自己最大的优势是什么？请用具体例子说明。"],
        "rubric": [
            {"criterion": "结构化表达", "weight": 0.5, "description": "结论先行、逻辑清晰"},
            {"criterion": "岗位匹配", "weight": 0.5, "description": "突出与目标岗位相关的亮点"},
        ],
    },
    {
        "section": "项目深挖",
        "difficulty": 3,
        "target_competency": "项目深挖",
        "question": "挑一个你最有代表性的项目详细讲讲，包括背景、你的角色、遇到的难点和最终结果。",
        "followups": ["如果让你重做这个项目，你会做哪些改进？"],
        "rubric": [
            {"criterion": "项目清晰度", "weight": 0.4, "description": "背景/角色/行动/结果完整"},
            {"criterion": "深度", "weight": 0.3, "description": "能讲清难点与取舍"},
            {"criterion": "量化结果", "weight": 0.3, "description": "有数据支撑"},
        ],
    },
    {
        "section": "专业技能",
        "difficulty": 3,
        "target_competency": "通用技术",
        "question": "针对{position}，你最熟悉的技术栈是什么？请结合项目说明你掌握到什么程度。",
        "followups": ["最近有学习新的技术吗？如何学习的？"],
        "rubric": [
            {"criterion": "技术深度", "weight": 0.5, "description": "掌握原理而不只是会用"},
            {"criterion": "实战经验", "weight": 0.5, "description": "有真实项目落地"},
        ],
    },
    {
        "section": "行为面试",
        "difficulty": 2,
        "target_competency": "行为面试",
        "question": "讲一次你遇到严重冲突或失败的经历，你是如何应对和总结的？",
        "followups": ["这件事之后你改变了自己哪些做法？"],
        "rubric": [
            {"criterion": "STAR 结构", "weight": 0.5, "description": "情境/任务/行动/结果完整"},
            {"criterion": "复盘能力", "weight": 0.5, "description": "有真实反思而非空话"},
        ],
    },
    {
        "section": "专业技能",
        "difficulty": 4,
        "target_competency": "通用技术",
        "question": "如果让你从零设计一个{position}相关的核心系统/功能，你会怎么思考？请说明你的设计思路。",
        "followups": ["这个方案在扩展性上如何考虑？"],
        "rubric": [
            {"criterion": "思路框架", "weight": 0.4, "description": "需求→模块→扩展"},
            {"criterion": "深度", "weight": 0.3, "description": "能讲清关键技术点"},
            {"criterion": "沟通", "weight": 0.3, "description": "表达清晰有条理"},
        ],
    },
    {
        "section": "自我认知",
        "difficulty": 2,
        "target_competency": "沟通表达",
        "question": "你未来 1-2 年的职业规划是什么？为什么选择{position}方向？",
        "followups": ["你觉得自己离理想岗位还差哪些能力？准备怎么补？"],
        "rubric": [
            {"criterion": "目标感", "weight": 0.5, "description": "规划清晰可行"},
            {"criterion": "自我认知", "weight": 0.5, "description": "能客观认识差距"},
        ],
    },
]


# ═══════════════════════════════════════════════════════════
# H2 纯函数状态机（current_question / current_prompt / advance / is_complete）
# 只操作 sim 对象（dict 或 ORM），不读时钟、不随机——完全可测。
# ═══════════════════════════════════════════════════════════


def current_question(sim) -> dict | None:
    """返回 cursor 处的题目 dict；越界返回 None。"""
    plan = sim.plan or []
    if 0 <= sim.cursor < len(plan):
        return plan[sim.cursor]
    return None


def current_followup(sim) -> str | None:
    """返回当前正在追问的追问文本；无追问（followup_index<0 或越界）返回 None。"""
    q = current_question(sim)
    if q is None:
        return None
    idx = sim.followup_index
    followups = q.get("followups") or []
    if 0 <= idx < len(followups):
        return followups[idx]
    return None


def current_prompt(sim) -> str:
    """返回当前要展示给用户的文本：追问优先，否则主问题。"""
    followup = current_followup(sim)
    if followup is not None:
        return followup
    q = current_question(sim)
    return q["text"] if q else ""


def is_complete(sim) -> bool:
    """cursor 越过最后一道题即为完成。"""
    return sim.cursor >= len(sim.plan or [])


def _is_followup_pending(sim) -> bool:
    """当前题目是否还有未问的追问（含当前正在问的那一题之后是否还有）。"""
    q = current_question(sim)
    if q is None:
        return False
    nf = len(q.get("followups") or [])
    return sim.followup_index + 1 < nf


def advance(sim) -> bool:
    """推进一步：追问未问完 → 推进追问；否则 cursor+1 重置追问。

    Returns:
        True=推进后仍有下一题可展示；False=已越过末尾（is_complete）。
    """
    if _is_followup_pending(sim):
        sim.followup_index += 1
        return True
    sim.cursor += 1
    sim.followup_index = -1
    return sim.cursor < len(sim.plan or [])


def skip_question(sim) -> bool:
    """跳过当前整题（含未答的追问）：cursor 直接越过本题。

    与 advance 不同：skip 不展示当前题的追问，直接到下一题。
    """
    sim.cursor += 1
    sim.followup_index = -1
    return sim.cursor < len(sim.plan or [])


def _current_question_id(sim) -> str:
    q = current_question(sim)
    return q["id"] if q else ""


# ═══════════════════════════════════════════════════════════
# H1 题单生成（LLM + 确定性模板兜底）
# ═══════════════════════════════════════════════════════════


_SYSTEM_PLAN = (
    "你是资深面试教练。基于候选人简历和目标岗位，生成一份模拟面试题单。\n"
    "要求：\n"
    "1. 生成 6-8 道题，覆盖：自我介绍/项目深挖/专业技能/行为面试/自我认知 等板块；\n"
    "2. 每道题为一个 JSON 对象，含字段：\n"
    "   id（q1,q2,...）、text（问题正文，中文）、section（板块名）、difficulty、\n"
    "   rubric（评分维度数组，每项 {criterion, weight, description}，weight 之和约为 1）、\n"
    "   followups、target_competency（技能维度名，"
    "如：算法/数据结构/系统设计/数据库/操作系统/计算机网络/项目深挖/行为面试/沟通表达）；\n"
    "3. 问题必须基于简历中的实际经历与技能，追问要能深挖细节，不得编造简历中没有的事实。\n"
    "只输出 JSON 数组（不要 Markdown 代码块，不要任何解释文字）。"
)


def _parse_plan_json(text: str) -> list[dict] | None:
    """从 LLM 输出中提取题单 JSON 数组；失败返回 None。"""
    if not text:
        return None
    cleaned = text.strip()
    # 剥离可能的 Markdown 代码围栏
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"\s*```$", "", cleaned, flags=re.MULTILINE)
    # 找第一个 [ 到最后一个 ]
    start = cleaned.find("[")
    end = cleaned.rfind("]")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        data = json.loads(cleaned[start : end + 1])
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(data, list):
        return None
    return _sanitize_plan(data)


def _sanitize_plan(questions: list) -> list[dict]:
    """过滤/规整题单元素，保证每项都含关键字段（坏项丢弃）。"""
    out: list[dict] = []
    for i, raw in enumerate(questions, start=1):
        if not isinstance(raw, dict):
            continue
        text = str(raw.get("text") or "").strip()
        if not text:
            continue
        followups = raw.get("followups")
        if not isinstance(followups, list):
            followups = []
        followups = [str(f).strip() for f in followups if isinstance(f, str) and str(f).strip()][:2]
        rubric = raw.get("rubric")
        if not isinstance(rubric, list):
            rubric = []
        clean_rubric = []
        for r in rubric:
            if isinstance(r, dict) and str(r.get("criterion") or "").strip():
                clean_rubric.append(
                    {
                        "criterion": str(r["criterion"]).strip(),
                        "weight": float(r.get("weight", 1)) if isinstance(r.get("weight"), (int, float)) else 1.0,
                        "description": str(r.get("description") or "").strip(),
                    }
                )
        try:
            difficulty = int(raw.get("difficulty", 3))
            difficulty = max(1, min(5, difficulty))
        except (TypeError, ValueError):
            difficulty = 3
        out.append(
            {
                "id": f"q{len(out) + 1}",
                "text": text,
                "section": str(raw.get("section") or "综合").strip()[:20],
                "difficulty": difficulty,
                "rubric": clean_rubric,
                "followups": followups,
                "target_competency": str(raw.get("target_competency") or "通用能力").strip()[:20],
            }
        )
        if len(out) >= MAX_PLAN_QUESTIONS:
            break
    return out


def _template_plan(target_position: str, resume_text: str) -> list[dict]:
    """确定性模板兜底题单（LLM 不可用时）。基于岗位关键词偏置技能维度。"""
    text = (resume_text or "").lower()
    # 技能维度关键词偏置（粗粒度，够用即可）
    comp_hits: dict[str, int] = {
        "算法": sum(1 for k in ("算法", "leetcode", "动态规划", "排序") if k in text),
        "数据结构": sum(1 for k in ("数据结构", "链表", "树", "哈希", "堆", "栈") if k in text),
        "数据库": sum(1 for k in ("数据库", "mysql", "redis", "sql", "索引") if k in text),
        "操作系统": sum(1 for k in ("操作系统", "进程", "线程", "内存", "并发") if k in text),
        "计算机网络": sum(1 for k in ("网络", "tcp", "http", "协议") if k in text),
        "系统设计": sum(1 for k in ("架构", "系统设计", "高并发", "分布式", "微服务") if k in text),
        "项目深挖": sum(1 for k in ("项目", "开发", "上线", "落地") if k in text),
    }
    top_comp = max(comp_hits, key=comp_hits.get) if max(comp_hits.values(), default=0) > 0 else "通用技术"

    plan: list[dict] = []
    for i, tpl in enumerate(_TEMPLATE_SECTIONS, start=1):
        question = tpl["question"].format(position=target_position)
        followups = [f.format(position=target_position) for f in tpl["followups"]]
        # 技能类模板若命中简历关键词，替换为该技能维度
        comp = top_comp if tpl["target_competency"] == "通用技术" else tpl["target_competency"]
        plan.append(
            {
                "id": f"q{i}",
                "text": question,
                "section": tpl["section"],
                "difficulty": tpl["difficulty"],
                "rubric": tpl["rubric"],
                "followups": followups,
                "target_competency": comp,
            }
        )
    return plan


async def generate_plan(
    *,
    target_position: str,
    resume_text: str,
    user_id: int | None = None,
) -> list[dict]:
    """生成题单：LLM 生成 + 确定性模板兜底。best-effort，绝不抛错。"""
    from services.rag.pipeline import llm_generate

    try:
        raw = await llm_generate(
            system=_SYSTEM_PLAN,
            user=(
                f"目标岗位：{target_position}\n\n"
                f"候选人简历：\n{resume_text[:8000] or '（简历为空，请按岗位通用问题出题）'}"
            ),
            temperature=0.5,
            max_tokens=3000,
            user_id=user_id,
            scenario="qa_complex",
        )
        plan = _parse_plan_json(raw)
        if plan and len(plan) >= MIN_PLAN_QUESTIONS:
            return plan
        logger.warning("interview_coach: LLM 题单解析失败/题数不足，回退模板（len=%s）", len(plan or []))
    except Exception as e:  # noqa: BLE001 - 兜底保证
        logger.warning("interview_coach: LLM 题单生成失败，回退模板: %s", e)
    return _template_plan(target_position, resume_text)


# ═══════════════════════════════════════════════════════════
# 会话存取（interview_simulations）
# ═══════════════════════════════════════════════════════════


async def get_active_simulation(
    db: AsyncSession, user_id: int, resume_id: int | None
) -> InterviewSimulation | None:
    """查用户进行中的模拟面试。

    resume_id 给定 → 精确匹配 (user_id, resume_id)；
    否则 → 用户最新一条 active 记录（要求唯一，多/无返回 None 由调用方提示）。
    """
    stmt = (
        select(InterviewSimulation)
        .where(
            InterviewSimulation.user_id == user_id,
            InterviewSimulation.status == "active",
        )
        .order_by(InterviewSimulation.updated_at.desc())
    )
    if resume_id is not None:
        stmt = stmt.where(InterviewSimulation.resume_id == resume_id)
    result = await db.execute(stmt.limit(5))
    # 防御性转 list：真实 SQLAlchemy scalars().all() 本就是 list，此处仅兜底
    rows = list(result.scalars().all())
    if not rows:
        return None
    if resume_id is not None:
        return rows[0]
    # 无 resume_id：仅当唯一时才自动续接，避免歧义
    return rows[0] if len(rows) == 1 else None


async def start_simulation(
    db: AsyncSession,
    user_id: int,
    resume_id: int,
    target_position: str,
    resume_text: str,
) -> InterviewSimulation:
    """新建一场模拟面试：生成题单 + 初始化状态。"""
    plan = await generate_plan(
        target_position=target_position,
        resume_text=resume_text,
        user_id=user_id,
    )
    sim = InterviewSimulation(
        user_id=user_id,
        resume_id=resume_id,
        target_position=target_position,
        plan=plan,
        cursor=0,
        followup_index=-1,
        answers=[],
        status="active",
    )
    db.add(sim)
    await db.commit()
    await db.refresh(sim)
    return sim


def _get_answer_record(sim: InterviewSimulation, question_id: str) -> dict | None:
    for rec in sim.answers or []:
        if isinstance(rec, dict) and rec.get("question_id") == question_id:
            return rec
    return None


def record_answer(sim: InterviewSimulation, answer: str) -> None:
    """把当前用户回答记录到「当前正在回答的那一题」。

    - followup_index == -1 → 记为主回答（answer 字段）
    - followup_index >= 0  → 追加到 followups_asked（含追问原文）
    """
    q = current_question(sim)
    if q is None:
        return
    qid = q["id"]
    sim.answers = list(sim.answers or [])
    rec = _get_answer_record(sim, qid)
    if rec is None:
        rec = {"question_id": qid, "answer": "", "followups_asked": []}
        sim.answers.append(rec)
    if sim.followup_index >= 0:
        rec.setdefault("followups_asked", [])
        rec["followups_asked"].append(
            {"prompt": q.get("followups", [])[sim.followup_index] if sim.followup_index < len(q.get("followups") or []) else "", "answer": answer}
        )
    else:
        rec["answer"] = (rec.get("answer") or "") + answer


# ═══════════════════════════════════════════════════════════
# H3 评分（LLM 逐题评分 + 确定性启发式兜底）→ ScoreCard → 写入 InterviewSession
# ═══════════════════════════════════════════════════════════

_SCORE_SYSTEM = (
    "你是严格的面试评分官。对每题的回答按 0-100 打分（<60 不合格，60-69 及格，"
    "70-79 良好，80-89 优秀，>=90 卓越），并给出简短反馈和一段高质量参考回答。\n"
    "只输出 JSON 数组，每项为 {\"question_id\": \"q1\", \"score\": 0-100 整数, "
    "\"feedback\": \"一句话反馈\", \"model_answer\": \"参考回答\"}。"
)


def _heuristic_score(rec: dict) -> int:
    """确定性兜底评分：按回答篇幅 + 追问完成度估算（无 LLM 依赖）。"""
    main = rec.get("answer") or ""
    chars = len(re.sub(r"\s+", "", main))
    if chars < 20:
        score = 40
    elif chars < 50:
        score = 55
    elif chars < 100:
        score = 65
    elif chars < 200:
        score = 75
    else:
        score = 85
    followups = rec.get("followups_asked") or []
    if followups:
        score = min(95, score + 5 * len(followups))
    return max(30, min(95, score))


async def _score_answers(
    plan: list[dict],
    answers: list[dict],
    user_id: int | None,
) -> dict:
    """逐题评分：LLM 批量打分 + 启发式兜底。

    Returns:
        {question_id: {"score": int, "feedback": str, "model_answer": str}}
    """
    from services.rag.pipeline import llm_generate

    # 收集已答（主回答非空 或 有追问）
    answered: list[dict] = []
    for q in plan:
        rec = next((a for a in answers if isinstance(a, dict) and a.get("question_id") == q["id"]), None)
        if rec and (str(rec.get("answer") or "").strip() or rec.get("followups_asked")):
            answered.append({"question": q, "answer": rec})

    scores: dict[str, dict] = {}
    if answered:
        try:
            prompt_parts = []
            for item in answered:
                q = item["question"]
                rec = item["answer"]
                prompt_parts.append(
                    f"题目[{q['id']}]（板块:{q['section']} 难度:{q['difficulty']}）: {q['text']}\n"
                    f"评分维度: {q.get('rubric') or []}\n"
                    f"候选人回答: {rec.get('answer') or '（未回答主问题）'}\n"
                    + ("".join(f"追问: {fa.get('prompt')} → {fa.get('answer')}\n" for fa in rec.get("followups_asked") or []))
                )
            raw = await llm_generate(
                system=_SCORE_SYSTEM,
                user="\n".join(prompt_parts),
                temperature=0.2,
                max_tokens=2000,
                user_id=user_id,
                scenario="judge",
            )
            parsed = _parse_score_json(raw)
            if parsed:
                scores = parsed
        except Exception as e:  # noqa: BLE001 - 兜底保证
            logger.warning("interview_coach: LLM 评分失败，回退启发式: %s", e)

    # 未评到分的题回退启发式
    for item in answered:
        qid = item["question"]["id"]
        if qid not in scores:
            scores[qid] = {
                "score": _heuristic_score(item["answer"]),
                "feedback": "（启发式评分，按回答篇幅估算）",
                "model_answer": "",
            }
    return scores


def _parse_score_json(text: str) -> dict | None:
    """解析逐题评分 JSON 数组 → {question_id: {...}}；失败返回 None。"""
    if not text:
        return None
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"\s*```$", "", cleaned, flags=re.MULTILINE)
    start = cleaned.find("[")
    end = cleaned.rfind("]")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        data = json.loads(cleaned[start : end + 1])
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(data, list):
        return None
    out: dict[str, dict] = {}
    for item in data:
        if not isinstance(item, dict):
            continue
        qid = str(item.get("question_id") or "")
        if not qid:
            continue
        try:
            score = int(item.get("score", 0))
        except (TypeError, ValueError):
            score = 0
        score = max(0, min(100, score))
        out[qid] = {
            "score": score,
            "feedback": str(item.get("feedback") or "").strip(),
            "model_answer": str(item.get("model_answer") or "").strip(),
        }
    return out or None


def build_scorecard(
    plan: list[dict],
    answers: list[dict],
    question_scores: dict[str, dict],
) -> dict:
    """聚合 ScoreCard（形状对齐 interview_service.derive_weak_competencies 消费契约）。

    scorecard:
        {
          "overall_score": int,
          "competency_scores": [{"competency": str, "score": int, "evidence": str}],
          "weak_competencies": [str],
          "strengths": [str],
          "weaknesses": [str],
          "model_answers": [{"question_id", "answer"}],
          "next_steps": [str],
          "coverage_pct": float,
          "notes": str,
          "summary": str,
        }
    """
    # 已答题目（有分数）
    comp_map: dict[str, list[int]] = {}
    per_q: list[dict] = []
    total_answered = 0
    for q in plan:
        rec = next((a for a in answers if isinstance(a, dict) and a.get("question_id") == q["id"]), None)
        has_answer = rec and (str(rec.get("answer") or "").strip() or rec.get("followups_asked"))
        if not has_answer or q["id"] not in question_scores:
            continue
        total_answered += 1
        comp = q.get("target_competency") or "通用能力"
        comp_map.setdefault(comp, []).append(question_scores[q["id"]]["score"])
        per_q.append(
            {
                "question_id": q["id"],
                "text": q["text"],
                "score": question_scores[q["id"]]["score"],
                "model_answer": question_scores[q["id"]].get("model_answer", ""),
            }
        )

    competency_scores = sorted(
        (
            {
                "competency": comp,
                "score": round(sum(v) / len(v)),
                "evidence": f"{len(v)} 题平均分",
            }
            for comp, v in comp_map.items()
        ),
        key=lambda c: c["score"],
        reverse=True,
    )
    overall = round(sum(c["score"] for c in competency_scores) / len(competency_scores)) if competency_scores else 0
    weak = [c["competency"] for c in competency_scores if c["score"] < WEAK_SCORE_THRESHOLD]
    strengths = [f"{c['competency']}（{c['score']}）" for c in competency_scores[:2] if c["score"] >= 75]
    weaknesses = [f"{c['competency']}（{c['score']}）" for c in competency_scores if c["score"] < WEAK_SCORE_THRESHOLD]
    next_steps = _build_next_steps(weak)
    coverage = round(total_answered / len(plan), 2) if plan else 1.0

    return {
        "overall_score": overall,
        "competency_scores": competency_scores,
        "weak_competencies": weak,
        "strengths": strengths,
        "weaknesses": weaknesses,
        "model_answers": [
            {"question_id": p["question_id"], "answer": p["model_answer"]} for p in per_q if p["model_answer"]
        ],
        "next_steps": next_steps,
        "coverage_pct": coverage,
        "notes": f"共 {total_answered}/{len(plan)} 题有回答，覆盖率 {coverage:.0%}",
        "summary": (
            f"总分 {overall}，覆盖 {total_answered}/{len(plan)} 题。"
            + (f"薄弱项：{'、'.join(weak)}。" if weak else "无明显薄弱项，继续保持。")
        ),
    }


def _build_next_steps(weak: list[str]) -> list[str]:
    """确定性下一步建议（对齐 interview_service._MODULE_TEMPLATES 的模块名）。"""
    steps: list[str] = []
    for comp in weak:
        title_map = {
            "算法": "算法专项刷题",
            "数据结构": "数据结构查漏补缺",
            "系统设计": "系统设计方法论训练",
            "项目深挖": "项目经历 STAR 复盘",
            "数据库": "数据库原理与优化",
            "操作系统": "操作系统核心概念梳理",
            "计算机网络": "计算机网络分层回顾",
            "沟通表达": "表达结构化训练",
            "行为面试": "行为面试素材打磨",
        }
        steps.append(f"【{comp}】建议：{title_map.get(comp, f'强化 {comp}')}，并针对薄弱维度复盘重练。")
    return steps or ["保持状态，继续多轮模拟面试巩固。"]


async def finalize_simulation(
    db: AsyncSession,
    user_id: int,
    sim: InterviewSimulation,
) -> tuple[dict, dict]:
    """结束并评分一场模拟面试。

    - 逐题评分 → ScoreCard
    - 写入 InterviewSession（公司=模拟面试，复用复盘闭环）
    - 标记 sim completed

    Returns:
        (scorecard, interview_session)
    """
    from services import interview_service

    plan = sim.plan or []
    answers = sim.answers or []
    question_scores = await _score_answers(plan, answers, user_id=user_id)
    scorecard = build_scorecard(plan, answers, question_scores)

    session = await interview_service.create_interview(
        db,
        user_id,
        company=COMPANY_LABEL,
        position=sim.target_position,
        resume_id=sim.resume_id,
        questions=[q["text"] for q in plan],
        answers=[a.get("answer", "") for a in answers if isinstance(a, dict)],
        notes="AI 模拟面试自动评分",
        scorecard=scorecard,
    )

    sim.status = "completed"
    sim.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(sim)
    return scorecard, session


# ═══════════════════════════════════════════════════════════
# 面向工具/调用的高层入口
# ═══════════════════════════════════════════════════════════


def format_question(sim: InterviewSimulation, *, is_first: bool = False) -> str:
    """把当前一步格式化为用户可见的提示文本。"""
    plan = sim.plan or []
    total = len(plan)
    q = current_question(sim)
    if q is None:
        return ""
    n = sim.cursor + 1
    followup = current_followup(sim)
    header = (
        f"🎤 模拟面试开始 — 目标岗位：{sim.target_position}\n\n"
        if is_first
        else ""
    )
    if followup is not None:
        body = f"【追问 {sim.followup_index + 1}】{followup}"
        tip = "\n\n> 继续回答即可。想跳过这题直接说「跳过」，想提前结束说「结束面试」。"
    else:
        rubric = "；".join(f"{r.get('criterion')}(权重{r.get('weight')})" for r in (q.get("rubric") or []))
        body = (
            f"【第 {n}/{total} 题 · {q.get('section', '综合')} · 难度 {q.get('difficulty', 3)}】"
            f"{q['text']}"
        )
        if rubric:
            body += f"\n\n考察点：{rubric}"
        tip = "\n\n> 直接回答即可，答完我会继续追问或出下一题。想跳过说「跳过」，想提前结束说「结束面试」。"
    return header + body + tip


def format_scorecard_result(scorecard: dict, sim: InterviewSimulation) -> str:
    """把 ScoreCard 格式化为用户可见结果 + 结构化块（供前端/Agent 提取）。"""
    lines = [
        f"🎉 模拟面试结束（{sim.target_position}）！评分卡已生成，并同步到「面试复盘」。",
        "",
        f"## 总分：{scorecard['overall_score']}/100",
        f"覆盖 {scorecard.get('notes', '')}",
        "",
        "### 各维度",
    ]
    for c in scorecard.get("competency_scores", []):
        mark = "⚠️" if c["score"] < WEAK_SCORE_THRESHOLD else "✅"
        lines.append(f"- {mark} {c['competency']}: {c['score']}")
    if scorecard.get("weak_competencies"):
        lines.append("")
        lines.append("### 薄弱项")
        lines.extend(f"- {w}" for w in scorecard["weak_competencies"])
    if scorecard.get("strengths"):
        lines.append("")
        lines.append("### 优势")
        lines.extend(f"- {s}" for s in scorecard["strengths"])
    if scorecard.get("model_answers"):
        lines.append("")
        lines.append("### 参考回答精选")
        for m in scorecard["model_answers"][:3]:
            lines.append(f"- {m['question_id']}：{m['answer'][:120]}")
    if scorecard.get("next_steps"):
        lines.append("")
        lines.append("### 下一步建议")
        lines.extend(f"- {s}" for s in scorecard["next_steps"])
    lines.append("")
    lines.append(
        "<interview_scorecard>"
        + json.dumps(scorecard, ensure_ascii=False)
        + "</interview_scorecard>"
    )
    return "\n".join(lines)
