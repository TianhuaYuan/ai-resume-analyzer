"""投递状态机服务（J 功能，阶段 5，third_party/Job recruit.py STATUS_FLOW 对照）。

- 状态流转：校验 STATUS_FLOW 合法性（面试轮次可跳过，已编码在流图里），
  timeline 自动追加，终态（Offer/已拒）不可流转。
- JD 评分卡：创建/更新时可选生成（LLM + 模板兜底），grade A-F / comp_min_max /
  pain_line / gaps。
- 去重：matchKeys + normalizeJobUrl——同岗位多来源只显示一次，新建时检测已有近似记录。
- 软删除：deleted_at 标记 → 垃圾箱可恢复；列表默认排除已删除。
- 看板：截止日期红黄绿（≤3 天红 / ≤7 天黄 / 其余绿 / 过期）、停留 >14 天提醒、
  今日队列（致谢/催办/失联，时序规则常量可调，对齐 fieldwork TimingSettings 默认）。
"""

import json
import logging
import re
from datetime import date, datetime, timedelta, timezone
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions import AppException
from models.job_application import JobApplication

logger = logging.getLogger(__name__)

# ── 状态机常量（third_party/Job recruit.py STATUS_FLOW 同构）──
STATUSES = ["待投递", "已投递", "笔试", "一面", "二面", "三面", "HR面", "Offer", "已拒"]
TERMINAL_STATUSES = ["Offer", "已拒"]
STATUS_FLOW: dict[str, list[str]] = {
    "待投递": ["已投递"],
    "已投递": ["笔试", "一面", "已拒"],
    "笔试": ["一面", "已拒"],
    "一面": ["二面", "三面", "HR面", "Offer", "已拒"],
    "二面": ["三面", "HR面", "Offer", "已拒"],
    "三面": ["HR面", "Offer", "已拒"],
    "HR面": ["Offer", "已拒"],
    "Offer": [],
    "已拒": [],
}
VALID_PRIORITIES = ["高", "中", "低"]

# 看板时序规则常量（fieldwork TimingSettings 默认对照：thankyou_hours=24,
# nudge_days=7, ghost_days=30）。此处可调：致谢 24h / 催办 7 天 / 失联 14 天。
THANKYOU_HOURS = 24
NUDGE_DAYS = 7
GHOST_DAYS = 14
STAY_WARN_DAYS = 14  # 停留提醒阈值（>14 天）

# 看板/列表里算停留天数的时间基点：最后一条 timeline 时间，无则 created_at
def _last_active_at(app: JobApplication) -> datetime:
    if app.timeline:
        try:
            last = app.timeline[-1]
            if isinstance(last, dict) and last.get("at"):
                return datetime.fromisoformat(str(last["at"]).replace("Z", "+00:00"))
        except (ValueError, TypeError, IndexError):
            pass
    return app.created_at


def compute_stay_days(app: JobApplication, today: date | None = None) -> int | None:
    """停留天数 = 距最近一次状态更新的天数；无时间线/创建时间时返回 None。"""
    base = _last_active_at(app)
    if base is None:
        return None
    today = today or date.today()
    return (today - base.date()).days


def deadline_status(app: JobApplication, today: date | None = None) -> str:
    """截止日期状态：overdue / red / yellow / green / none。"""
    if not app.deadline:
        return "none"
    today = today or date.today()
    diff = (app.deadline - today).days
    if diff < 0:
        return "overdue"
    if diff <= 3:
        return "red"
    if diff <= 7:
        return "yellow"
    return "green"


# ── URL 归一化 + matchKeys 去重（fieldwork dedupe 思路）──

# 丢弃的追踪参数（归一化 URL 用）
_TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "spm", "from", "source", "src", "share_token", "wechat", "_x", "xcode",
}


def normalize_job_url(url: str | None) -> str:
    """归一化岗位链接：小写 scheme/host、去尾斜杠、丢弃追踪参数、参数排序。"""
    if not url:
        return ""
    try:
        parts = urlsplit(url.strip())
        if not parts.scheme or not parts.netloc:
            return url.strip().lower().rstrip("/")
        keep = [
            (k, v)
            for k, v in parse_qsl(parts.query)
            if k.lower() not in _TRACKING_PARAMS
        ]
        keep.sort()
        query = urlencode(keep) if keep else ""
        path = parts.path.rstrip("/")
        return urlunsplit(
            (parts.scheme.lower(), parts.netloc.lower(), path, query, "")
        )
    except Exception:  # noqa: BLE001 - 兜底
        return url.strip().lower().rstrip("/")


def _normalize_text(s: str) -> str:
    """归一化文本用于去重键：去空白与标点，保留字母数字与中文。"""
    if not s:
        return ""
    s = s.lower().strip()
    return re.sub(r"[\s\W_]+", "", s, flags=re.UNICODE) or ""


def derive_match_keys(company: str, position: str, url: str | None) -> list[str]:
    """派生去重键集合：company+position 归一键 + company 键 + 归一 URL 键。"""
    keys: set[str] = set()
    c, p = _normalize_text(company), _normalize_text(position)
    if c and p:
        keys.add(f"cp:{c}:{p}")
    if c:
        keys.add(f"c:{c}")
    nu = normalize_job_url(url)
    if nu:
        keys.add(f"url:{nu}")
    return sorted(keys)


async def _find_duplicates(
    db: AsyncSession, user_id: int, match_keys: list[str], normalized_url: str | None, *,
    exclude_id: int | None = None,
) -> list[JobApplication]:
    """查同用户已有近似记录（非软删除）用于去重提示/合并。"""
    if not match_keys and not normalized_url:
        return []
    stmt = select(JobApplication).where(
        JobApplication.user_id == user_id,
        JobApplication.deleted_at.is_(None),
    )
    if exclude_id is not None:
        stmt = stmt.where(JobApplication.id != exclude_id)
    result = await db.execute(stmt)
    rows = result.scalars().all()
    dupes: list[JobApplication] = []
    for row in rows:
        row_keys = row.match_keys or []
        row_nu = row.normalized_url or ""
        if match_keys and set(match_keys) & set(row_keys):
            dupes.append(row)
            continue
        if (
            normalized_url
            and row_nu
            and normalized_url == row_nu
        ):
            dupes.append(row)
    return dupes


# ── JD 评分卡（LLM + 模板兜底）──

_SCORECARD_SYSTEM = (
    "你是招聘分析专家。根据岗位 JD 生成一份投递评分卡（供求职者评估是否值得投递）。\n"
    "只输出 JSON 对象，字段：\n"
    '{"grade": "A-F", "comp_min": 年薪下限万/年或null, "comp_max": 年薪上限万/年或null, '
    '"pain_line": "核心要求/痛点一句话", "gaps": ["JD 中较难满足的硬性要求，可能为空"]}\n'
    "grade 含义：A=高度匹配且吸引力强，优先投递；B=匹配良好；C=一般；D=匹配较弱；F=不建议投递。\n"
    "薪资未写明则 comp_min/comp_max 为 null。只输出 JSON，不要解释文字。"
)


def _parse_scorecard_json(text: str) -> dict | None:
    if not text:
        return None
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"\s*```$", "", cleaned, flags=re.MULTILINE)
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        data = json.loads(cleaned[start : end + 1])
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    return data


def _template_scorecard(jd_text: str) -> dict:
    """确定性模板兜底评分卡。"""
    return {
        "grade": "C",
        "comp_min": None,
        "comp_max": None,
        "pain_line": (jd_text or "").strip()[:80] + ("…" if jd_text and len(jd_text) > 80 else ""),
        "gaps": [],
    }


async def generate_jd_scorecard(db, user_id: int, jd_text: str) -> dict:
    """生成 JD 评分卡（LLM + 模板兜底，best-effort 不抛错）。"""
    from services.rag.pipeline import llm_generate

    card: dict | None = None
    try:
        raw = await llm_generate(
            system=_SCORECARD_SYSTEM,
            user=f"岗位 JD：\n{jd_text[:6000]}",
            temperature=0.2,
            max_tokens=800,
            user_id=user_id,
            scenario="resume_compare",
        )
        parsed = _parse_scorecard_json(raw)
        if parsed:
            grade = str(parsed.get("grade", "C")).strip().upper()[:1]
            if grade not in "ABCDF":
                grade = "C"
            card = {
                "grade": grade,
                "comp_min": parsed.get("comp_min"),
                "comp_max": parsed.get("comp_max"),
                "pain_line": str(parsed.get("pain_line") or "").strip()[:200],
                "gaps": [
                    str(g).strip() for g in (parsed.get("gaps") or [])
                    if isinstance(g, str) and str(g).strip()
                ][:10],
            }
    except Exception as e:  # noqa: BLE001 - 兜底保证
        logger.warning("job_application: JD 评分卡 LLM 失败，回退模板: %s", e)
    if card is None:
        card = _template_scorecard(jd_text)
    card["generated_at"] = datetime.now(timezone.utc).isoformat()
    return card


# ── CRUD ──────────────────────────────────────────────────────


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def create_application(
    db: AsyncSession,
    user_id: int,
    *,
    company: str,
    position: str,
    url: str | None = None,
    status: str = "待投递",
    priority: str = "中",
    deadline: date | None = None,
    notes: str | None = None,
    jd_text: str | None = None,
    generate_scorecard: bool = False,
) -> tuple[JobApplication, list[JobApplication]]:
    """创建投递记录。返回 (记录, 检测到的重复记录列表)。"""
    company = (company or "").strip()
    position = (position or "").strip()
    if not company or not position:
        raise AppException(status_code=422, detail="公司名与岗位名不能为空")
    if status not in STATUSES:
        raise AppException(status_code=422, detail=f"无效状态，合法值：{' / '.join(STATUSES)}")
    if priority not in VALID_PRIORITIES:
        raise AppException(status_code=422, detail=f"无效优先级，合法值：{' / '.join(VALID_PRIORITIES)}")

    match_keys = derive_match_keys(company, position, url)
    normalized_url = normalize_job_url(url)
    dupes = await _find_duplicates(db, user_id, match_keys, normalized_url)

    scorecard = None
    if generate_scorecard and jd_text and jd_text.strip():
        scorecard = await generate_jd_scorecard(db, user_id, jd_text)

    now_iso = _now_iso()
    app = JobApplication(
        user_id=user_id,
        company=company,
        position=position,
        url=url,
        status=status,
        priority=priority,
        deadline=deadline,
        notes=notes,
        jd_text=jd_text,
        jd_scorecard=scorecard,
        match_keys=match_keys,
        normalized_url=normalized_url or None,
        timeline=[{"at": now_iso, "from": "", "to": status, "note": "创建记录"}],
    )
    db.add(app)
    await db.commit()
    await db.refresh(app)
    return app, dupes


async def list_applications(
    db: AsyncSession,
    user_id: int,
    *,
    status: str | None = None,
    priority: str | None = None,
    keyword: str | None = None,
    deleted: bool = False,
    page: int = 1,
    limit: int = 50,
) -> tuple[list[JobApplication], int]:
    """分页列表（默认排除软删除）。支持 status/priority/keyword 过滤。"""
    conditions = [JobApplication.user_id == user_id]
    if deleted:
        conditions.append(JobApplication.deleted_at.isnot(None))
    else:
        conditions.append(JobApplication.deleted_at.is_(None))
    if status:
        conditions.append(JobApplication.status == status)
    if priority:
        conditions.append(JobApplication.priority == priority)
    if keyword:
        kw = f"%{keyword}%"
        conditions.append(
            or_(
                JobApplication.company.ilike(kw),
                JobApplication.position.ilike(kw),
                JobApplication.notes.ilike(kw),
            )
        )

    total = (
        await db.execute(
            select(func.count()).select_from(JobApplication).where(*conditions)
        )
    ).scalar_one()
    result = await db.execute(
        select(JobApplication)
        .where(*conditions)
        .order_by(JobApplication.updated_at.desc())
        .offset((page - 1) * limit)
        .limit(limit)
    )
    return result.scalars().all(), total


async def get_application(db: AsyncSession, user_id: int, application_id: int) -> JobApplication:
    """查单条（含软删除，允许垃圾箱恢复场景）；非本人 → 404。"""
    result = await db.execute(
        select(JobApplication).where(
            JobApplication.id == application_id,
            JobApplication.user_id == user_id,
        )
    )
    app = result.scalar_one_or_none()
    if app is None:
        raise AppException(status_code=404, detail="投递记录不存在或无权访问")
    return app


async def update_application(
    db: AsyncSession,
    user_id: int,
    application_id: int,
    *,
    company: str | None = None,
    position: str | None = None,
    url: str | None = None,
    priority: str | None = None,
    deadline: date | None = None,
    notes: str | None = None,
    jd_text: str | None = None,
    generate_scorecard: bool = False,
) -> tuple[JobApplication, list[JobApplication]]:
    """更新投递记录（不含状态流转，状态用 transition_status）。"""
    app = await get_application(db, user_id, application_id)
    if company is not None:
        app.company = (company or "").strip() or app.company
    if position is not None:
        app.position = (position or "").strip() or app.position
    if url is not None:
        app.url = url or None
        app.normalized_url = normalize_job_url(url) or None
    if priority is not None:
        if priority not in VALID_PRIORITIES:
            raise AppException(status_code=422, detail=f"无效优先级，合法值：{' / '.join(VALID_PRIORITIES)}")
        app.priority = priority
    if deadline is not None:
        app.deadline = deadline
    if notes is not None:
        app.notes = notes
    if jd_text is not None:
        app.jd_text = jd_text
        if generate_scorecard and jd_text.strip():
            app.jd_scorecard = await generate_jd_scorecard(db, user_id, jd_text)
    elif generate_scorecard and app.jd_text and app.jd_text.strip():
        app.jd_scorecard = await generate_jd_scorecard(db, user_id, app.jd_text)

    # 重新派生去重键
    app.match_keys = derive_match_keys(app.company, app.position, app.url)
    dupes = await _find_duplicates(
        db, user_id, app.match_keys, app.normalized_url, exclude_id=app.id
    )

    await db.commit()
    await db.refresh(app)
    return app, dupes


async def transition_status(
    db: AsyncSession,
    user_id: int,
    application_id: int,
    *,
    new_status: str,
    note: str | None = None,
) -> JobApplication:
    """状态流转：校验 STATUS_FLOW 合法性，timeline 自动追加。"""
    if new_status not in STATUSES:
        raise AppException(status_code=422, detail=f"无效状态，合法值：{' / '.join(STATUSES)}")
    app = await get_application(db, user_id, application_id)
    old = app.status
    if old in TERMINAL_STATUSES:
        raise AppException(status_code=400, detail=f"「{old}」为终态，不可再流转")
    if new_status == old:
        return app
    allowed = STATUS_FLOW.get(old, [])
    if new_status not in allowed:
        raise AppException(
            status_code=400,
            detail=f"非法流转：「{old}」只能流向 {' / '.join(allowed) or '（终态，不可流转）'}",
        )
    app.timeline = list(app.timeline or [])
    app.timeline.append(
        {"at": _now_iso(), "from": old, "to": new_status, "note": (note or "").strip()}
    )
    app.status = new_status
    await db.commit()
    await db.refresh(app)
    return app


async def soft_delete(db: AsyncSession, user_id: int, application_id: int) -> None:
    """软删除（进垃圾箱）。"""
    app = await get_application(db, user_id, application_id)
    if app.deleted_at is not None:
        return
    app.deleted_at = datetime.now(timezone.utc)
    await db.commit()


async def restore_application(db: AsyncSession, user_id: int, application_id: int) -> JobApplication:
    """从垃圾箱恢复（deleted_at 置空）。"""
    app = await get_application(db, user_id, application_id)
    app.deleted_at = None
    await db.commit()
    await db.refresh(app)
    return app


# ── 看板（今日队列：致谢/催办/失联；时序规则常量可调）──

INTERVIEW_ROUNDS = {"一面", "二面", "三面", "HR面"}
ACTIVE_STATUSES = {"已投递", "笔试", "一面", "二面", "三面", "HR面"}


def _latest_status_change(app: JobApplication) -> dict | None:
    if not app.timeline:
        return None
    return app.timeline[-1] if isinstance(app.timeline[-1], dict) else None


def build_queue(app: JobApplication, now: datetime) -> dict | None:
    """为单条投递派生今日队列项（致谢/催办/失联之一），无则 None。

    - thank_you 致谢：最近一次状态变更进入面试轮次（一面/二面/三面/HR面），
      且距该变更 ≤ THANKYOU_HOURS，提示发送致谢/反馈。
    - nudge 催办：状态在面试轮次，停留 > NUDGE_DAYS，提示礼貌催办。
    - ghost 失联：状态在活跃态，停留 > GHOST_DAYS，提示失联跟进/判断止损。
    """
    if app.deleted_at is not None or app.status in TERMINAL_STATUSES:
        return None
    stay = compute_stay_days(app)
    last = _latest_status_change(app)

    # 致谢（面试轮次后 24h 内）
    if app.status in INTERVIEW_ROUNDS and last and last.get("to") in INTERVIEW_ROUNDS:
        try:
            changed = datetime.fromisoformat(str(last["at"]).replace("Z", "+00:00"))
            hours_since = (now - changed).total_seconds() / 3600
            if 0 <= hours_since <= THANKYOU_HOURS:
                return {
                    "kind": "thank_you",
                    "headline": f"发送致谢 — {app.company}",
                    "detail": f"{app.position} · 进入{app.status} {int(hours_since)} 小时前",
                }
        except (ValueError, TypeError):
            pass

    # 失联（活跃态停留超限）——优先于催办（更严重）
    if app.status in ACTIVE_STATUSES and stay is not None and stay > GHOST_DAYS:
        return {
            "kind": "ghost",
            "headline": f"疑似失联 — {app.company}",
            "detail": f"{app.position} · {app.status} 停留 {stay} 天无进展，建议跟进或止损",
        }

    # 催办（面试轮次停留超限）
    if app.status in INTERVIEW_ROUNDS and stay is not None and stay > NUDGE_DAYS:
        return {
            "kind": "nudge",
            "headline": f"催办跟进 — {app.company}",
            "detail": f"{app.position} · {app.status} 停留 {stay} 天，可礼貌询问进展",
        }

    return None


async def build_dashboard(
    db: AsyncSession, user_id: int, now: datetime | None = None
) -> dict:
    """看板数据：统计 + 截止红黄绿 + 今日队列（致谢/催办/失联）。"""
    now = now or datetime.now(timezone.utc)
    today = now.date()
    result = await db.execute(
        select(JobApplication).where(
            JobApplication.user_id == user_id,
            JobApplication.deleted_at.is_(None),
        )
    )
    apps = result.scalars().all()

    stats = {
        "total": len(apps),
        "active": sum(1 for a in apps if a.status in ACTIVE_STATUSES),
        "to_apply": sum(1 for a in apps if a.status == "待投递"),
        "offer": sum(1 for a in apps if a.status == "Offer"),
        "rejected": sum(1 for a in apps if a.status == "已拒"),
        "high_priority": sum(1 for a in apps if a.priority == "高"),
    }
    deadline_counts = {"red": 0, "yellow": 0, "green": 0, "overdue": 0, "none": 0}
    for a in apps:
        ds = deadline_status(a, today)
        deadline_counts[ds] = deadline_counts.get(ds, 0) + 1

    queue: list[dict] = []
    for a in apps:
        item = build_queue(a, now)
        if item:
            queue.append(
                {
                    **item,
                    "application_id": a.id,
                    "company": a.company,
                    "position": a.position,
                    "priority": a.priority,
                    "status": a.status,
                    "stay_days": compute_stay_days(a, today),
                }
            )
    # 排序：致谢/失联优先于催办，其次按停留天数降序
    _kind_rank = {"thank_you": 0, "ghost": 1, "nudge": 2}
    queue.sort(key=lambda q: (_kind_rank.get(q["kind"], 3), -(q["stay_days"] or 0)))

    return {
        "timing": {"thankyou_hours": THANKYOU_HOURS, "nudge_days": NUDGE_DAYS, "ghost_days": GHOST_DAYS},
        "stats": stats,
        "deadline_counts": deadline_counts,
        "queue": queue,
    }
