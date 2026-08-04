"""T37: 产品分析 API。

- POST /analytics/events    记录产品事件（登录用户，30/min 限流防滥用）
- GET  /analytics/events    管理员查询事件列表
- GET  /analytics/funnel    管理员查看漏斗聚合数据
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_current_user, require_admin
from core.database import get_db
from core.limiter import limiter
from models.user import User
from schemas.analytics import (
    AnalyticsEventListResponse,
    AnalyticsEventRequest,
    AnalyticsEventResponse,
    FunnelResponse,
    LLMUsageItem,
    LLMUsageResponse,
    TrendItem,
    TrendResponse,
)
from services.analytics_service import get_funnel, get_trends, list_events, record_event

# prefix 用 /track 而非 /analytics：路径含 "analytics" 会被浏览器广告拦截扩展
# （如 uBlock/AdGuard）整条拦截 → net::ERR_BLOCKED_BY_CLIENT，产品埋点丢失。
router = APIRouter(prefix="/track", tags=["analytics"])


@router.post("/events", response_model=AnalyticsEventResponse, status_code=200)
@limiter.limit("30/minute")
async def post_event(
    request: Request,
    data: AnalyticsEventRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """记录一条产品事件（best-effort 写入，失败不影响核心流程）。"""
    event = await record_event(
        db,
        user_id=current_user.id,
        event_name=data.event_name,
        source=data.source,
        metadata=data.metadata,
    )
    if event is None:
        # 显式埋点写入失败应可见（前端仍会静默吞掉）
        raise HTTPException(status_code=500, detail="事件写入失败")
    return event


@router.get("/events", response_model=AnalyticsEventListResponse)
async def get_events(
    event_name: str | None = Query(None, description="按事件名过滤"),
    source: str | None = Query(None, description="按来源渠道过滤"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    """管理员分页查询事件列表。"""
    items, total = await list_events(
        db, event_name=event_name, source=source, limit=limit, offset=offset
    )
    return AnalyticsEventListResponse(
        items=[AnalyticsEventResponse.model_validate(it) for it in items],
        total=total,
    )


@router.get("/funnel", response_model=FunnelResponse)
async def get_funnel_endpoint(
    days: int = Query(30, ge=1, le=365, description="统计最近 N 天"),
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    """管理员查看漏斗数据：各事件的总次数与去重用户数。"""
    events = await get_funnel(db, days=days)
    return FunnelResponse(events=events, days=days)


@router.get("/trends", response_model=TrendResponse)
async def get_trends_endpoint(
    days: int = Query(30, ge=1, le=365, description="统计最近 N 天"),
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    """D3: 管理员查看按天趋势（注册/日活/事件数），供后台看板图表。"""
    items = await get_trends(db, days=days)
    return TrendResponse(days=days, items=[TrendItem(**it) for it in items])


@router.get("/llm-usage", response_model=LLMUsageResponse)
async def get_llm_usage_endpoint(
    days: int = Query(7, ge=1, le=90, description="统计最近 N 天"),
    _admin: User = Depends(require_admin),
):
    """D4: 管理员查看 LLM 用量历史（按天聚合，跨全部用户，来自 Redis 记账）。"""
    from services.rag.usage import get_usage_summary

    items = await get_usage_summary(days=days)
    return LLMUsageResponse(days=days, items=[LLMUsageItem(**it) for it in items])
