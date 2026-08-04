"""校招求职复盘纯函数层（对齐 third_party/fieldwork insights.ts + todayQueue.ts 的纯函数）。

全部纯函数、无 I/O：输入 CampusTrack ORM 行 + CampusTrackEvent 行（或等价 dict，
见 _field 兼容器），输出统计 dict。日期一律用 datetime.date。
"""

from datetime import date, datetime

# 阶段阶梯：offer 既是终态又是阶梯最高级；rejected/cancelled 不在此阶梯上。
STATUS_LADDER: list[str] = [
    "applied",
    "pending_written",
    "written_passed",
    "first_round",
    "second_round",
    "third_round",
    "offer",
]

# 终态：offer 在阶梯上；rejected/cancelled 不在。
TERMINAL_STATUSES: set[str] = {"offer", "rejected", "cancelled"}

# 活跃（非终态、非待投递）状态 —— ghost 判定 + Active KPI 共用
_ACTIVE_STATUSES: set[str] = {
    "applied",
    "pending_written",
    "written_passed",
    "first_round",
    "second_round",
    "third_round",
}


def _field(obj, name: str, default=None):
    """从 ORM 行或 dict 取字段（纯函数层不绑 ORM，便于单测构造）。"""
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _ladder_index(status) -> int:
    if not status:
        return -1
    try:
        return STATUS_LADDER.index(status)
    except ValueError:
        return -1


# ── 阶段归一化 ────────────────────────────────────────────────


def normalize_stage_reached(raw: str | None) -> str | None:
    """把自由文本阶段备注（stage_reached，手写如 "三面后挂"）归一化到阶梯阶段。

    顺序重要：先查最深关键词。无匹配返回 None（真·未知）。
    """
    if not raw:
        return None
    s = str(raw).lower()
    if "offer" in s or "accepted" in s:
        return "offer"
    if ("third" in s or "3rd" in s or "final" in s or "三面" in s or "终面" in s
            or "hr面" in s):
        return "third_round"
    if "second" in s or "2nd" in s or "二面" in s:
        return "second_round"
    if ("first" in s or "1st" in s or "一面" in s or "interview" in s
            or "onsite" in s or "on-site" in s or "panel" in s or "loop" in s):
        return "first_round"
    if "written_passed" in s or "written passed" in s or "笔试通过" in s or "通过笔试" in s:
        return "written_passed"
    if "written" in s or "笔试" in s or "test" in s or "assessment" in s or "ccat" in s:
        return "pending_written"
    if "applied" in s or "application" in s or "已投递" in s or "投递" in s:
        return "applied"
    return None


def _event_stage(ev) -> str | None:
    """事件证明到达的阶梯阶段（无证明返回 None）。

    - applied         → applied（用户投递）
    - status_change   → to_status（取 to/from 中较深、且在阶梯上的）
    - interview       → to_status，或至少 first_round（进了面）
    - rejection       → from_status（被拒前到达的阶段）
    - note            → 不证明任何阶段
    """
    etype = _field(ev, "event_type")
    if etype == "applied":
        return "applied"
    if etype == "interview":
        to = _field(ev, "to_status")
        if to in STATUS_LADDER:
            return to
        return "first_round"
    if etype == "status_change":
        for s in (_field(ev, "to_status"), _field(ev, "from_status")):
            if s in STATUS_LADDER:
                return s
        return None
    if etype == "rejection":
        fr = _field(ev, "from_status")
        return fr if fr in STATUS_LADDER else None
    return None


# ── 最远到达阶段 ──────────────────────────────────────────────


def compute_reached(tracks, events) -> dict[str, int]:
    """最远到达阶段下标（status + events + stage_reached 取最深）。

    阶梯索引：STATUS_LADDER.index(...)；-1 = 未投递（pending）。
    终局态（rejected/cancelled）至少算 applied（0）；offer 本身就在阶梯上。
    key 用 campus_record_id（事件以它关联 track，且 (user_id, campus_record_id) 唯一）。
    """
    events_by_track: dict[str, list] = {}
    for ev in events:
        rid = _field(ev, "campus_record_id")
        if not rid:
            continue
        events_by_track.setdefault(rid, []).append(ev)

    reached: dict[str, int] = {}
    for track in tracks:
        rid = _field(track, "campus_record_id")
        if not rid:
            continue
        status = _field(track, "status")

        idx = _ladder_index(status)
        if idx < 0 and status in TERMINAL_STATUSES:
            idx = 0  # 终局态至少 applied

        for ev in events_by_track.get(rid, []):
            stage = _event_stage(ev)
            if stage:
                idx = max(idx, _ladder_index(stage))

        normalized = normalize_stage_reached(_field(track, "stage_reached"))
        if normalized:
            idx = max(idx, _ladder_index(normalized))

        reached[rid] = idx
    return reached


# ── 漏斗 ──────────────────────────────────────────────────────


def build_funnel(tracks) -> list[dict]:
    """当前状态分布（快照漏斗），按 campus_status.STATUSES 顺序含零。"""
    from services.campus_status import STATUSES

    counts = {s: 0 for s in STATUSES}
    for track in tracks:
        status = _field(track, "status")
        if status in counts:
            counts[status] += 1
    return [{"status": s, "count": counts[s]} for s in STATUSES]


# ── KPI ───────────────────────────────────────────────────────


def _first_response_dates(tracks, events) -> dict[str, date]:
    """每份 track 的首次公司回响日期（进入更深阶梯的 status_change / interview）。

    回响 = 对方真实互动：status_change 进 pending_written+（index>=1）或 interview 事件。
    投递（applied）与拒信（rejection）不算正向回响 —— 对齐 insights.ts 仅 screen/round/offer。
    """
    out: dict[str, date] = {}
    for ev in events:
        rid = _field(ev, "campus_record_id")
        if not rid:
            continue
        etype = _field(ev, "event_type")
        if etype == "status_change":
            to = _field(ev, "to_status")
            if to not in STATUS_LADDER or _ladder_index(to) < 1:
                continue
        elif etype != "interview":
            continue
        occurred = _field(ev, "occurred_at")
        if not isinstance(occurred, date):
            continue
        cur = out.get(rid)
        if cur is None or occurred < cur:
            out[rid] = occurred
    return out


def build_kpis(tracks, reached, events) -> dict:
    """核心 KPI。分母 = 已投递（非 pending）；reached 中终局态至少算 applied。

    返回 dict：
      applied           已投递数（非 pending）
      active            当前活跃数（applied..third_round）
      response_rate     回响率（reached>=pending_written）0~1
      interview_rate    面试率（reached>=first_round）0~1
      offer_rate        Offer 率（reached>=offer）0~1
      ghost_count       当前幽灵候选数（超 30 天无联系且无未来面试）
      avg_response_days 平均回响天数（有日期可算时），无则 None
    """
    total_tracks = [t for t in tracks if _field(t, "status") != "pending"]
    total = len(total_tracks)

    def reached_of(track) -> int:
        return reached.get(_field(track, "campus_record_id"), -1)

    responded = sum(1 for t in total_tracks if reached_of(t) >= 1)
    interviewed = sum(1 for t in total_tracks if reached_of(t) >= _ladder_index("first_round"))
    offered = sum(1 for t in total_tracks if reached_of(t) >= _ladder_index("offer"))
    active = sum(1 for t in tracks if _field(t, "status") in _ACTIVE_STATUSES)

    ghost_count = len(find_ghost_candidates(tracks, events))

    first_resp = _first_response_dates(tracks, events)
    gaps: list[int] = []
    for t in total_tracks:
        resp = first_resp.get(_field(t, "campus_record_id"))
        applied_on = _field(t, "date_applied")
        if resp is None or not isinstance(applied_on, date):
            continue
        days = (resp - applied_on).days
        if days >= 0:
            gaps.append(days)
    avg_response_days = round(sum(gaps) / len(gaps)) if gaps else None

    def pct(num: int, denom: int) -> float:
        return round(num / denom, 4) if denom else 0.0

    return {
        "applied": total,
        "active": active,
        "response_rate": pct(responded, total),
        "interview_rate": pct(interviewed, total),
        "offer_rate": pct(offered, total),
        "ghost_count": ghost_count,
        "avg_response_days": avg_response_days,
    }


# ── 阶段转化 ──────────────────────────────────────────────────


def build_stage_conversion(tracks, reached) -> list[dict]:
    """相邻阶梯逐级转化（"漏斗在哪漏"视图）。count = 到达 to 阶段的人数。"""
    counts: list[int] = []
    for i in range(len(STATUS_LADDER)):
        counts.append(
            sum(1 for t in tracks if reached.get(_field(t, "campus_record_id"), -1) >= i)
        )

    steps: list[dict] = []
    for i in range(1, len(STATUS_LADDER)):
        prev = counts[i - 1]
        steps.append({
            "from": STATUS_LADDER[i - 1],
            "to": STATUS_LADDER[i],
            "count": counts[i],
            "rate": (counts[i] / prev) if prev else 0.0,
        })
    return steps


# ── 拒因聚类 ──────────────────────────────────────────────────


_REASON_BUCKETS: list[tuple[str, list[str]]] = [
    ("Internal / other candidate",
     ["internal candidate", "internal hire", "went with someone", "another candidate"]),
    ("Comp mismatch",
     ["comp", "salary", "budget", "compensation", "pay range"]),
    ("Overqualified / seniority mismatch",
     ["overqualified", "too senior", "too junior", "seniority", "not senior enough"]),
    ("Skills / experience gap",
     ["skills gap", "experience", "did not have", "didn't have", "lacked", "missing"]),
    ("Role paused / timing",
     ["paused", "put the role on hold", "timing", "position was closed",
      "role was cancelled", "on hold"]),
    ("Culture / team fit",
     ["culture fit", "team fit", "not the right fit", "wasn't the right fit"]),
    ("No reason given",
     ["no reason", "none given", "did not say", "didn't say"]),
]


def cluster_rejection_reasons(reasons: list[str]) -> list[dict]:
    """拒因关键词聚类（7 桶 + Other）。空串 → No reason；非空不匹配 → Other。

    刻意朴素（"doesn't need ML"）：按桶关键词取首个命中。
    """
    counts: dict[str, int] = {}
    for raw in reasons:
        combined = (raw or "").lower().strip()
        if not combined:
            counts["No reason given"] = counts.get("No reason given", 0) + 1
            continue
        matched = False
        for bucket, keywords in _REASON_BUCKETS:
            if bucket == "No reason given":
                continue
            if any(k and k in combined for k in keywords):
                counts[bucket] = counts.get(bucket, 0) + 1
                matched = True
                break
        if not matched:
            counts["Other"] = counts.get("Other", 0) + 1
    return [
        {"bucket": b, "count": c}
        for b, c in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    ]


# ── 幽灵判定 ──────────────────────────────────────────────────


def find_ghost_candidates(tracks, events, ghost_days: int = 30) -> list[dict]:
    """幽灵候选：状态 ∈ 活跃（applied..third_round）且超过 ghost_days 天无联系。

    最后联系日 = max(最新事件日期, date_applied)，两者皆无则 created_at 兜底
    （对齐 todayQueue.ts lastContactDate 语义）。
    存在未来面试事件（occurred_at 在今天之后）时阻断（对方并未失联）。
    """
    today = date.today()

    events_by_track: dict[str, list] = {}
    for ev in events:
        rid = _field(ev, "campus_record_id")
        if not rid:
            continue
        events_by_track.setdefault(rid, []).append(ev)

    candidates: list[dict] = []
    for track in tracks:
        rid = _field(track, "campus_record_id")
        status = _field(track, "status")
        if not rid or status not in _ACTIVE_STATUSES:
            continue

        track_events = events_by_track.get(rid, [])

        has_future_interview = any(
            _field(ev, "event_type") == "interview"
            and isinstance(_field(ev, "occurred_at"), date)
            and _field(ev, "occurred_at") > today
            for ev in track_events
        )
        if has_future_interview:
            continue

        dates: list[date] = [
            _field(ev, "occurred_at") for ev in track_events
            if isinstance(_field(ev, "occurred_at"), date)
        ]
        applied_on = _field(track, "date_applied")
        if isinstance(applied_on, date):
            dates.append(applied_on)
        if not dates:
            created = _field(track, "created_at")
            if isinstance(created, datetime):
                dates.append(created.date())
            elif isinstance(created, date):
                dates.append(created)
        if not dates:
            continue

        last_contact = max(dates)
        days_since = (today - last_contact).days
        if days_since >= ghost_days:
            candidates.append({
                "campus_record_id": rid,
                "days_since": days_since,
                "last_contact": last_contact,
            })
    return candidates
