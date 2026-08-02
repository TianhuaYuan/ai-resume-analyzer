"""市场数据 API（公共求职资产：岗位 / 范文）。

- 岗位浏览/详情：公开（无鉴权），数据来自 market_assets 表（is_expired 过滤）
- 范文列表/详情：公开；详情含结构化 payload（不含原文——合规）
- 岗位推荐：需鉴权（基于用户简历匹配）

攻略（guide）端点预留，数据抓取完成后补挂载。
"""

import logging
from math import ceil

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_current_user
from core.database import get_db
from models.market_asset import MarketAsset
from models.user import User
from schemas.market import (
    MarketGuideDetail,
    MarketGuideItem,
    MarketGuideListResponse,
    MarketJobDetail,
    MarketJobItem,
    MarketJobListResponse,
    MarketRecommendItem,
    MarketRecommendRequest,
    MarketRecommendResponse,
    MarketSampleDetail,
    MarketSampleItem,
    MarketSampleListResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/market", tags=["market"])


# ── 岗位浏览（公开） ─────────────────────────────────────────


@router.get("/jobs", response_model=MarketJobListResponse)
async def list_jobs(
    q: str = Query("", description="关键词搜索（title/company/position）"),
    job_type: str = Query("", description="校招/社招/实习：campus/social/intern"),
    source: str = Query("", description="数据源过滤"),
    city: str = Query("", description="城市过滤"),
    industry: str = Query("", description="行业过滤"),
    company: str = Query("", description="公司过滤"),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """岗位分页列表：默认只返回未过期（is_expired=False）的岗位。"""
    conditions = [MarketAsset.asset_type == "job", MarketAsset.is_expired == False]  # noqa: E712

    if job_type.strip():
        conditions.append(MarketAsset.job_type == job_type.strip())
    if source.strip():
        conditions.append(MarketAsset.source == source.strip())
    if city.strip():
        conditions.append(MarketAsset.city.like(f"%{city.strip()}%"))
    if industry.strip():
        conditions.append(MarketAsset.industry.like(f"%{industry.strip()}%"))
    if company.strip():
        conditions.append(MarketAsset.company.like(f"%{company.strip()}%"))
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
    result = await db.execute(
        select(MarketAsset)
        .where(*conditions)
        .order_by(MarketAsset.created_at.desc())
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


@router.get("/jobs/{asset_id}", response_model=MarketJobDetail)
async def get_job(asset_id: int, db: AsyncSession = Depends(get_db)):
    """岗位详情（含 content 全文）。"""
    result = await db.execute(
        select(MarketAsset).where(MarketAsset.id == asset_id, MarketAsset.asset_type == "job")
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="岗位不存在")
    return MarketJobDetail.model_validate(row)


# ── 范文浏览（公开，不含原文） ───────────────────────────────


@router.get("/samples", response_model=MarketSampleListResponse)
async def list_samples(
    q: str = Query("", description="关键词搜索（title/position）"),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """范文列表摘要（不含 payload / 原文）。"""
    conditions = [MarketAsset.asset_type == "sample"]
    if q.strip():
        kw = f"%{q.strip()}%"
        conditions.append(
            or_(MarketAsset.title.like(kw), MarketAsset.position.like(kw))
        )
    total = await db.scalar(select(func.count(MarketAsset.id)).where(*conditions))
    total = total or 0
    result = await db.execute(
        select(MarketAsset)
        .where(*conditions)
        .order_by(MarketAsset.created_at.desc())
        .offset((page - 1) * limit)
        .limit(limit)
    )
    items = result.scalars().all()
    return MarketSampleListResponse(
        items=[_sample_item(it) for it in items],
        total=total,
        page=page,
        limit=limit,
        total_pages=ceil(total / limit) if total else 0,
    )


def _sample_item(row: MarketAsset) -> MarketSampleItem:
    """把 MarketAsset 映射为范文摘要（category 存在 payload 中）。"""
    return MarketSampleItem(
        id=row.id,
        title=row.title,
        position=row.position,
        category=(row.payload or {}).get("category"),
        created_at=row.created_at,
    )


@router.get("/samples/{asset_id}", response_model=MarketSampleDetail)
async def get_sample(asset_id: int, db: AsyncSession = Depends(get_db)):
    """范文详情：含结构化 payload（{style, modules, target_position}），不含原文（合规）。"""
    result = await db.execute(
        select(MarketAsset).where(MarketAsset.id == asset_id, MarketAsset.asset_type == "sample")
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="范文不存在")
    return MarketSampleDetail(
        **(_sample_item(row).model_dump()),
        payload=row.payload,
    )


# ── 攻略浏览（公开） ─────────────────────────────────────────


def _guide_item(row: MarketAsset) -> MarketGuideItem:
    payload = row.payload or {}
    return MarketGuideItem(
        id=row.id,
        title=row.title,
        summary=row.content if row.asset_type == "guide" and len(row.content) < 500 else (payload.get("summary") or ""),
        date=payload.get("date"),
        url=payload.get("url"),
        has_fulltext=bool(payload.get("has_fulltext")),
    )


@router.get("/guides", response_model=MarketGuideListResponse)
async def list_guides(
    q: str = Query("", description="关键词搜索（title/content）"),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """攻略列表：正文未抓取时 content 即摘要，前端跳原文链接。"""
    conditions = [MarketAsset.asset_type == "guide"]
    if q.strip():
        kw = f"%{q.strip()}%"
        conditions.append(
            or_(MarketAsset.title.like(kw), MarketAsset.content.like(kw))
        )
    total = await db.scalar(select(func.count(MarketAsset.id)).where(*conditions))
    total = total or 0
    result = await db.execute(
        select(MarketAsset)
        .where(*conditions)
        .order_by(MarketAsset.created_at.desc())
        .offset((page - 1) * limit)
        .limit(limit)
    )
    items = result.scalars().all()
    return MarketGuideListResponse(
        items=[_guide_item(it) for it in items],
        total=total,
        page=page,
        limit=limit,
        total_pages=ceil(total / limit) if total else 0,
    )


@router.get("/guides/{asset_id}", response_model=MarketGuideDetail)
async def get_guide(asset_id: int, db: AsyncSession = Depends(get_db)):
    """攻略详情（content 为正文；未抓取时为摘要 + 跳原文）。"""
    result = await db.execute(
        select(MarketAsset).where(MarketAsset.id == asset_id, MarketAsset.asset_type == "guide")
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="攻略不存在")
    item = _guide_item(row)
    return MarketGuideDetail(**item.model_dump(), content=row.content)


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
