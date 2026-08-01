"""T37: 产品分析服务层。

提供事件记录（best-effort）、管理员事件列表、漏斗聚合三个能力。
所有函数均为 async，接收 AsyncSession。

设计原则：
- record_event 内部自吞异常（logger.warning），埋点失败绝不阻断核心业务流程
- 漏斗聚合按 event_name 分组，统计 count（事件总数）与 unique_users（去重用户数）
"""

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.analytics_event import AnalyticsEvent

logger = logging.getLogger(__name__)


async def record_event(
    db: AsyncSession,
    user_id: int | None,
    event_name: str,
    source: str | None = None,
    metadata: dict | None = None,
) -> AnalyticsEvent | None:
    """记录一条产品事件（best-effort）。

    失败仅打 warning 日志并回滚，绝不向上抛异常，
    保证调用方（注册/上传/导出等核心流程）不受埋点故障影响。
    """
    try:
        event = AnalyticsEvent(
            user_id=user_id,
            event_name=event_name,
            source=source,
            event_metadata=metadata,
        )
        db.add(event)
        await db.commit()
        await db.refresh(event)
        return event
    except Exception:
        logger.warning("记录产品事件失败: event_name=%s", event_name, exc_info=True)
        try:
            await db.rollback()
        except Exception:
            pass
        return None


async def list_events(
    db: AsyncSession,
    event_name: str | None = None,
    source: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[AnalyticsEvent], int]:
    """管理员查询事件列表，支持按 event_name / source 过滤，分页返回。"""
    stmt = select(AnalyticsEvent)
    count_stmt = select(func.count()).select_from(AnalyticsEvent)

    if event_name is not None:
        stmt = stmt.where(AnalyticsEvent.event_name == event_name)
        count_stmt = count_stmt.where(AnalyticsEvent.event_name == event_name)
    if source is not None:
        stmt = stmt.where(AnalyticsEvent.source == source)
        count_stmt = count_stmt.where(AnalyticsEvent.source == source)

    total = (await db.execute(count_stmt)).scalar_one()

    stmt = (
        stmt.order_by(AnalyticsEvent.created_at.desc(), AnalyticsEvent.id.desc())
        .limit(limit)
        .offset(offset)
    )
    items = (await db.execute(stmt)).scalars().all()
    return items, total


async def get_funnel(
    db: AsyncSession,
    days: int = 30,
) -> list[dict]:
    """漏斗聚合：统计最近 N 天内各事件的总次数与去重用户数。

    返回形如 [{"event_name": "user.register", "count": 10, "unique_users": 8}, ...]，
    按 count 降序排列，便于观察 注册 → 上传 → 构建 → 导出 的转化链路。
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    stmt = (
        select(
            AnalyticsEvent.event_name,
            func.count(AnalyticsEvent.id).label("count"),
            func.count(func.distinct(AnalyticsEvent.user_id)).label("unique_users"),
        )
        .where(AnalyticsEvent.created_at >= cutoff)
        .group_by(AnalyticsEvent.event_name)
        .order_by(func.count(AnalyticsEvent.id).desc())
    )
    rows = (await db.execute(stmt)).all()
    return [
        {"event_name": r.event_name, "count": r.count, "unique_users": r.unique_users}
        for r in rows
    ]
