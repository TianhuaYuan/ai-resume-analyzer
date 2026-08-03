"""市场数据 API（公共求职资产：岗位 / 范文 / 攻略 / 模板画廊）。

- 岗位浏览/详情：公开（无鉴权），数据来自 market_assets 表（is_expired 过滤）
- 岗位统计：公开，供校招页统计卡（总数/近3日/近7日/Top 行业）
- 范文列表/详情：公开；详情含结构化 payload（不含原文——合规）
- 攻略列表/详情：公开
- 简历模板画廊：公开，真实模板元数据 + 零数据渲染预览 HTML
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
    MarketGuideDetail,
    MarketGuideItem,
    MarketGuideListResponse,
    MarketJobDetail,
    MarketJobItem,
    MarketJobListResponse,
    MarketJobStatsResponse,
    MarketRecommendItem,
    MarketRecommendRequest,
    MarketRecommendResponse,
    MarketSampleDetail,
    MarketSampleItem,
    MarketSampleListResponse,
    MarketTemplateInfo,
    MarketTemplateListResponse,
)
from services.sample_module_service import build_sample_payload
from services.template_catalog import get_template_info, list_template_infos

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
    source: str = Query("", description="数据源过滤"),
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
    # 按发布时间排序：优先 payload.published_at（真实发布时间），缺失回退 created_at（入库时间）。
    # MySQL 用 json_unquote + date_format；SQLite（测试环境）无 date_format，回退简化排序。
    dialect_name = getattr(getattr(db.bind, "dialect", None), "name", "mysql")
    if dialect_name == "sqlite":
        published_expr = func.coalesce(
            func.json_extract(MarketAsset.payload, "$.published_at"),
            MarketAsset.created_at,
        )
    else:
        published_expr = func.coalesce(
            func.json_unquote(func.json_extract(MarketAsset.payload, "$.published_at")),
            func.date_format(MarketAsset.created_at, "%Y-%m-%dT%H:%i:%s"),
        )
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
    source: str = Query("", description="数据源过滤"),
    db: AsyncSession = Depends(get_db),
):
    """岗位统计（校招页统计卡）：总数 / 近3日 / 近7日 / Top 行业。"""
    conditions = [MarketAsset.asset_type == "job", MarketAsset.is_expired == False]  # noqa: E712
    if job_type.strip():
        conditions.append(MarketAsset.job_type == job_type.strip())
    if source.strip():
        conditions.append(MarketAsset.source == source.strip())

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
    """范文详情：含结构化 payload（{style, modules, target_position}），不含原文（合规）。

    存量范文 payload 可能缺 modules（同步时未生成），此处惰性生成并写回 DB，
    二次访问直接读。生成失败降级 modules=[]（前端走 AI 改写路径）。
    """
    result = await db.execute(
        select(MarketAsset).where(MarketAsset.id == asset_id, MarketAsset.asset_type == "sample")
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="范文不存在")
    payload = row.payload or {}
    if "modules" not in payload:
        payload = build_sample_payload(row.content or "", payload)
        row.payload = payload
        await db.commit()
    return MarketSampleDetail(
        **(_sample_item(row).model_dump()),
        content=row.content or "",
        payload=payload,
    )


# ── 攻略浏览（公开） ─────────────────────────────────────────


def _guide_item(row: MarketAsset) -> MarketGuideItem:
    """攻略列表项：有全文时用 payload.summary，否则用 content（即摘要）。"""
    payload = row.payload or {}
    has_fulltext = bool(payload.get("has_fulltext"))
    summary = payload.get("summary") if has_fulltext else row.content
    return MarketGuideItem(
        id=row.id,
        title=row.title,
        summary=summary or "",
        date=payload.get("date"),
        url=payload.get("url"),
        has_fulltext=has_fulltext,
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


# ── 简历模板画廊（公开） ─────────────────────────────────────


@router.get("/templates", response_model=MarketTemplateListResponse)
async def list_templates():
    """简历模板画廊：真实模板元数据 + 零数据渲染预览 HTML。"""
    return MarketTemplateListResponse(
        items=[MarketTemplateInfo(**it) for it in list_template_infos()]
    )


@router.get("/templates/{template_id}", response_model=MarketTemplateInfo)
async def get_template(template_id: str):
    """单套简历模板信息。未知模板 404。"""
    info = get_template_info(template_id)
    if info is None:
        raise HTTPException(status_code=404, detail="模板不存在")
    return MarketTemplateInfo(**info)


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
