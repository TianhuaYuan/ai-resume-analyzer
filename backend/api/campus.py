"""
campus.py — 校招 + 内推信息 API。

数据来源：从 offer.gfjianli.com 爬取的 JSON 文件。
- campus_recruitment.json：校招（约 10K+ 条）
- referral_recruitment.json：内推（约 289 条）
启动时加载到内存，提供分页 + 搜索 + 高级筛选 + 统计接口。
另有用户求职跟踪（进度 + 备注）需要认证。
"""

import json
import logging
from datetime import date, datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_current_user
from core.database import get_db
from core.exceptions import AppException
from models.campus_track import CampusTrack
from models.campus_track_event import CampusTrackEvent
from models.user import User
from services import campus_review, campus_status

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/campus", tags=["campus"])

# ── 数据加载 ──────────────────────────────────────────────────

_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
_records: list[dict] = []


def _load_data():
    """启动时加载两个 JSON 文件并合并到内存。"""
    global _records
    all_records: list[dict] = []
    for fname in ("campus_recruitment.json", "referral_recruitment.json"):
        fpath = _DATA_DIR / fname
        if not fpath.exists():
            logger.warning("campus data file not found: %s", fpath)
            continue
        with open(fpath, "r", encoding="utf-8") as f:
            raw = json.load(f)
        items = raw.get("data", [])
        all_records.extend(items)
        logger.info("Loaded %d records from %s", len(items), fpath.name)

    _records = all_records


_load_data()

# ── 工具函数 ──────────────────────────────────────────────────


def _parse_date(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.strptime(s[:10], "%Y-%m-%d")
    except (ValueError, TypeError):
        return None


def _filter_records(
    records: list[dict],
    *,
    q: str = "",
    info_type: str = "",
    industry: str = "",
    work_location: str = "",
    positions: str = "",
    date_from: str = "",
    date_to: str = "",
) -> list[dict]:
    """通用筛选逻辑：关键词搜索 + 类型 + 行业 + 地点 + 岗位 + 日期范围。"""
    result = records

    if q.strip():
        kw = q.strip().lower()
        result = [
            r for r in result
            if kw in (r.get("company") or "").lower()
            or kw in (r.get("title") or "").lower()
            or kw in (r.get("positions") or "").lower()
            or kw in (r.get("workLocation") or "").lower()
            or kw in (r.get("industry") or "").lower()
        ]

    if info_type.strip():
        result = [r for r in result if (r.get("infoType") or "") == info_type.strip()]

    if industry.strip():
        ind = industry.strip().lower()
        result = [r for r in result if ind in (r.get("industry") or "").lower()]

    if work_location.strip():
        loc = work_location.strip().lower()
        result = [r for r in result if loc in (r.get("workLocation") or "").lower()]

    if positions.strip():
        pos = positions.strip().lower()
        result = [r for r in result if pos in (r.get("positions") or "").lower()]

    dt_from = _parse_date(date_from) if date_from else None
    dt_to = _parse_date(date_to) if date_to else None
    if dt_from or dt_to:
        filtered = []
        for r in result:
            dt = _parse_date(r.get("recordTime"))
            if not dt:
                continue
            if dt_from and dt < dt_from:
                continue
            if dt_to and dt > dt_to:
                continue
            filtered.append(r)
        result = filtered

    return result


# ── 统计接口 ──────────────────────────────────────────────────


@router.get("/stats")
def get_stats(
    info_type: str = Query("", description="按 infoType 筛选（校招/内推）"),
):
    """返回数据统计：总条数、近3天更新、近7天更新。"""
    records = _filter_records(_records, info_type=info_type)
    now = datetime.now()
    d3 = now - timedelta(days=3)
    d7 = now - timedelta(days=7)

    count_3d = 0
    count_7d = 0
    for r in records:
        dt = _parse_date(r.get("recordTime"))
        if dt and dt >= d3:
            count_3d += 1
        if dt and dt >= d7:
            count_7d += 1

    industry_count: dict[str, int] = {}
    for r in records:
        ind = (r.get("industry") or "").strip()
        if ind:
            industry_count[ind] = industry_count.get(ind, 0) + 1
    top_industries = sorted(industry_count.items(), key=lambda x: -x[1])[:10]

    return {
        "total": len(records),
        "count_3d": count_3d,
        "count_7d": count_7d,
        "top_industries": [{"name": k, "count": v} for k, v in top_industries],
    }


# ── 搜索 + 分页 ─────────────────────────────────────────────


@router.get("/list")
def list_records(
    q: str = Query("", description="搜索关键词"),
    info_type: str = Query("", description="infoType 筛选"),
    industry: str = Query("", description="行业筛选"),
    work_location: str = Query("", description="工作地点筛选"),
    positions: str = Query("", description="岗位筛选"),
    date_from: str = Query("", description="开始日期 YYYY-MM-DD"),
    date_to: str = Query("", description="结束日期 YYYY-MM-DD"),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
):
    """分页 + 全面搜索 + 高级筛选。"""
    filtered = _filter_records(
        _records, q=q, info_type=info_type, industry=industry,
        work_location=work_location, positions=positions,
        date_from=date_from, date_to=date_to,
    )

    total = len(filtered)
    start = (page - 1) * limit
    end = start + limit
    items = filtered[start:end]

    return {
        "items": items,
        "total": total,
        "page": page,
        "limit": limit,
        "total_pages": (total + limit - 1) // limit,
    }


# ── 求职跟踪（需要认证） ──────────────────────────────────


class CampusTrackUpdate(BaseModel):
    campus_record_id: str
    status: str
    date_applied: date | None = None
    source: str | None = None
    rejection_reason: str | None = None
    stage_reached: str | None = None
    notes: str | None = None


class CampusTrackResponse(BaseModel):
    campus_record_id: str
    status: str
    date_applied: date | None = None
    source: str | None = None
    rejection_reason: str | None = None
    stage_reached: str | None = None
    notes: str | None = None


class CampusTracksMapResponse(BaseModel):
    tracks: dict[str, CampusTrackResponse]


@router.get("/tracks", response_model=CampusTracksMapResponse)
async def get_tracks(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取当前用户的所有求职跟踪记录。"""
    result = await db.execute(
        select(CampusTrack).where(CampusTrack.user_id == current_user.id)
    )
    rows = result.scalars().all()
    tracks = {}
    for row in rows:
        tracks[row.campus_record_id] = CampusTrackResponse(
            campus_record_id=row.campus_record_id,
            status=row.status,
            date_applied=row.date_applied,
            source=row.source,
            rejection_reason=row.rejection_reason,
            stage_reached=row.stage_reached,
            notes=row.notes,
        )
    return CampusTracksMapResponse(tracks=tracks)


@router.put("/tracks", response_model=CampusTrackResponse)
async def upsert_track(
    data: CampusTrackUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """创建或更新一条求职跟踪记录（upsert）。

    - 状态合法性 + 状态机转换校验（非法 → 400 AppException）
    - 状态变更时事务内追加一条 campus_track_events（from → to，occurred_at=今天）
    - 复盘字段（date_applied/source/rejection_reason/stage_reached）仅更新非空值，
      保持对旧前端（只发 campus_record_id/status/notes）兼容
    """
    try:
        campus_status.assert_valid_status(data.status)
    except ValueError as e:
        raise AppException(status_code=400, detail=str(e), error_code="INVALID_STATUS")

    result = await db.execute(
        select(CampusTrack).where(
            CampusTrack.user_id == current_user.id,
            CampusTrack.campus_record_id == data.campus_record_id,
        )
    )
    row = result.scalar_one_or_none()
    old_status = row.status if row else None

    if old_status is not None and old_status != data.status and not campus_status.can_transition(
        old_status, data.status
    ):
        allowed = ", ".join(campus_status.next_statuses(old_status))
        raise AppException(
            status_code=400,
            detail=f"非法状态转换: {old_status} → {data.status}（允许: {allowed}）",
            error_code="INVALID_STATUS_TRANSITION",
        )

    if row:
        if data.status != old_status:
            row.status = data.status
        if data.notes is not None:
            row.notes = data.notes
        if data.date_applied is not None:
            row.date_applied = data.date_applied
        if data.source is not None:
            row.source = data.source
        if data.rejection_reason is not None:
            row.rejection_reason = data.rejection_reason
        if data.stage_reached is not None:
            row.stage_reached = data.stage_reached
    else:
        row = CampusTrack(
            user_id=current_user.id,
            campus_record_id=data.campus_record_id,
            status=data.status,
            notes=data.notes,
            date_applied=data.date_applied,
            source=data.source,
            rejection_reason=data.rejection_reason,
            stage_reached=data.stage_reached,
        )
        db.add(row)

    # 状态变更 → 追加 ADD-only 事件（同状态 no-op / 新建行不产生事件）
    if old_status is not None and old_status != data.status:
        db.add(
            CampusTrackEvent(
                user_id=current_user.id,
                campus_record_id=data.campus_record_id,
                event_type="status_change",
                from_status=old_status,
                to_status=data.status,
                reason=data.rejection_reason if data.status == "rejected" else None,
                occurred_at=date.today(),
            )
        )

    await db.commit()
    await db.refresh(row)

    return CampusTrackResponse(
        campus_record_id=row.campus_record_id,
        status=row.status,
        date_applied=row.date_applied,
        source=row.source,
        rejection_reason=row.rejection_reason,
        stage_reached=row.stage_reached,
        notes=row.notes,
    )


@router.get("/review/summary")
async def get_review_summary(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """求职复盘总览（只读）：KPI + 漏斗 + 阶段转化 + 拒因聚类 + 幽灵候选。

    基于当前用户全部 track + 事件，统计逻辑在 services/campus_review.py（纯函数层）。
    """
    tracks_result = await db.execute(
        select(CampusTrack).where(CampusTrack.user_id == current_user.id)
    )
    tracks = tracks_result.scalars().all()

    events_result = await db.execute(
        select(CampusTrackEvent).where(CampusTrackEvent.user_id == current_user.id)
    )
    events = events_result.scalars().all()

    reached = campus_review.compute_reached(tracks, events)
    reasons = [
        t.rejection_reason for t in tracks
        if t.status == "rejected" and t.rejection_reason
    ]

    return {
        "kpis": campus_review.build_kpis(tracks, reached, events),
        "funnel": campus_review.build_funnel(tracks),
        "conversion": campus_review.build_stage_conversion(tracks, reached),
        "rejection_reasons": campus_review.cluster_rejection_reasons(reasons),
        "ghost_candidates": campus_review.find_ghost_candidates(tracks, events),
    }
