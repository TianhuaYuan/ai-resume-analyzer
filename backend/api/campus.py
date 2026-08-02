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
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi import status as http_status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_current_user
from core.database import get_db
from models.campus_track import CampusTrack
from models.user import User

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


class CampusTrackUpsert(BaseModel):
    campus_record_id: str
    status: str
    notes: str | None = None


class CampusTrackResponse(BaseModel):
    campus_record_id: str
    status: str
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
            notes=row.notes,
        )
    return CampusTracksMapResponse(tracks=tracks)


@router.put("/tracks", response_model=CampusTrackResponse)
async def upsert_track(
    data: CampusTrackUpsert,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """创建或更新一条求职跟踪记录（upsert）。"""
    valid_statuses = ["pending", "applied", "pending_written", "written_passed",
                       "first_round", "second_round", "third_round", "offer",
                       "rejected", "cancelled"]
    if data.status not in valid_statuses:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail=f"无效状态: {data.status}",
        )

    result = await db.execute(
        select(CampusTrack).where(
            CampusTrack.user_id == current_user.id,
            CampusTrack.campus_record_id == data.campus_record_id,
        )
    )
    row = result.scalar_one_or_none()

    if row:
        row.status = data.status
        row.notes = data.notes
    else:
        row = CampusTrack(
            user_id=current_user.id,
            campus_record_id=data.campus_record_id,
            status=data.status,
            notes=data.notes,
        )
        db.add(row)

    await db.commit()
    await db.refresh(row)

    return CampusTrackResponse(
        campus_record_id=row.campus_record_id,
        status=row.status,
        notes=row.notes,
    )
