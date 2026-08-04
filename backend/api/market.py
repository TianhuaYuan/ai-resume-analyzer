"""市场数据 API（公共求职资产：岗位）。

- 岗位浏览/详情：公开（无鉴权），数据来自 market_assets 表（is_expired 过滤）
- 岗位统计：公开，供校招页统计卡（总数/近3日/近7日/Top 行业）
- 岗位推荐：需鉴权（基于用户简历匹配）
"""

import logging
from datetime import datetime, timedelta
from math import ceil

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_current_user
from core.database import get_db
from models.market_asset import MarketAsset
from models.user import User
from schemas.market import (
    MarketJobDetail,
    MarketJobItem,
    MarketJobListResponse,
    MarketJobStatsResponse,
    MarketRecommendItem,
    MarketRecommendRequest,
    MarketRecommendResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/market", tags=["market"])


def _parse_date(s: str) -> datetime | None:
    """解析 YYYY-MM-DD 日期参数，非法返回 None。"""
    if not s:
        return None
    try:
        return datetime.strptime(s.strip()[:10], "%Y-%m-%d")
    except (ValueError, TypeError):
        return None


# ── 岗位浏览（公开） ─────────────────────────────────────────


@router.get("/jobs", response_model=MarketJobListResponse)
async def list_jobs(
    q: str = Query("", description="关键词搜索（title/company/position）"),
    job_type: str = Query("", description="校招/社招/实习：campus/social/intern"),
    city: str = Query("", description="城市过滤"),
    industry: str = Query("", description="行业过滤"),
    company: str = Query("", description="公司过滤"),
    position: str = Query("", description="岗位过滤"),
    date_from: str = Query("", description="发布日期起 YYYY-MM-DD（按 created_at）"),
    date_to: str = Query("", description="发布日期止 YYYY-MM-DD（按 created_at）"),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """岗位分页列表：默认只返回未过期（is_expired=False）的岗位。"""
    conditions = [MarketAsset.is_expired == False]  # noqa: E712

    if job_type.strip():
        conditions.append(MarketAsset.job_type == job_type.strip())
    if city.strip():
        conditions.append(MarketAsset.city.like(f"%{city.strip()}%"))
    if industry.strip():
        conditions.append(MarketAsset.industry.like(f"%{industry.strip()}%"))
    if company.strip():
        conditions.append(MarketAsset.company.like(f"%{company.strip()}%"))
    if position.strip():
        conditions.append(MarketAsset.position.like(f"%{position.strip()}%"))
    if date_from.strip():
        d0 = _parse_date(date_from)
        if d0:
            conditions.append(MarketAsset.created_at >= d0)
    if date_to.strip():
        d1 = _parse_date(date_to)
        if d1:
            conditions.append(MarketAsset.created_at < d1 + timedelta(days=1))
    if q.strip():
        kw = f"%{q.strip()}%"
        conditions.append(
            or_(
                MarketAsset.title.like(kw),
                MarketAsset.company.like(kw),
                MarketAsset.position.like(kw),
            )
        )

    total = await db.scalar(select(func.count(MarketAsset.id)).where(*conditions))
    total = total or 0
    # 按发布时间排序：优先 published_at（真实发布时间），缺失回退 created_at（入库时间）。
    published_expr = func.coalesce(MarketAsset.published_at, MarketAsset.created_at)
    result = await db.execute(
        select(MarketAsset)
        .where(*conditions)
        .order_by(published_expr.desc())
        .offset((page - 1) * limit)
        .limit(limit)
    )
    items = result.scalars().all()
    return MarketJobListResponse(
        items=[MarketJobItem.model_validate(it) for it in items],
        total=total,
        page=page,
        limit=limit,
        total_pages=ceil(total / limit) if total else 0,
    )


@router.get("/jobs/stats", response_model=MarketJobStatsResponse)
async def get_job_stats(
    job_type: str = Query("", description="校招/社招/实习：campus/social/intern"),
    db: AsyncSession = Depends(get_db),
):
    """岗位统计（校招页统计卡）：总数 / 近3日 / 近7日 / Top 行业。"""
    conditions = [MarketAsset.is_expired == False]  # noqa: E712
    if job_type.strip():
        conditions.append(MarketAsset.job_type == job_type.strip())

    total = await db.scalar(select(func.count(MarketAsset.id)).where(*conditions)) or 0

    now = datetime.now()
    d3 = now - timedelta(days=3)
    d7 = now - timedelta(days=7)
    count_3d = (
        await db.scalar(
            select(func.count(MarketAsset.id)).where(*conditions, MarketAsset.created_at >= d3)
        )
        or 0
    )
    count_7d = (
        await db.scalar(
            select(func.count(MarketAsset.id)).where(*conditions, MarketAsset.created_at >= d7)
        )
        or 0
    )

    industry_rows = await db.execute(
        select(MarketAsset.industry, func.count(MarketAsset.id))
        .where(*conditions, MarketAsset.industry.isnot(None), MarketAsset.industry != "")
        .group_by(MarketAsset.industry)
        .order_by(func.count(MarketAsset.id).desc())
        .limit(10)
    )
    top_industries = [{"name": name, "count": count} for name, count in industry_rows.all()]

    return MarketJobStatsResponse(
        total=total,
        count_3d=count_3d,
        count_7d=count_7d,
        top_industries=top_industries,
    )


@router.get("/jobs/{asset_id}", response_model=MarketJobDetail)
async def get_job(asset_id: int, db: AsyncSession = Depends(get_db)):
    """岗位详情（含 content 全文）。"""
    result = await db.execute(
        select(MarketAsset).where(MarketAsset.id == asset_id)
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="岗位不存在")
    return MarketJobDetail.model_validate(row)


# ── 岗位推荐（需鉴权） ───────────────────────────────────────


@router.post("/recommend", response_model=MarketRecommendResponse)
async def recommend_jobs(
    body: MarketRecommendRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """基于简历内容推荐匹配岗位（向量预筛 + LLM 精排）。"""
    from services.market_match_service import recommend_jobs as do_recommend

    items = await do_recommend(
        db,
        user_id=current_user.id,
        resume_id=body.resume_id,
        top_k=body.top_k,
        job_type=body.job_type,
    )
    return MarketRecommendResponse(items=[MarketRecommendItem(**it) for it in items])
