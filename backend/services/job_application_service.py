"""T33: 求职申请（Job Application）服务层。

CRUD + 看板聚合统计。所有操作均做 user_id 归属隔离，
非本人记录视为不存在（返回 404），避免泄露他人数据。
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.job_application import JobApplication
from schemas.job_application import JobApplicationCreate, JobApplicationUpdate


async def create_application(
    db: AsyncSession, user_id: int, data: JobApplicationCreate
) -> JobApplication:
    """创建一条求职申请。"""
    app = JobApplication(
        user_id=user_id,
        company=data.company,
        position=data.position,
        city=data.city,
        salary_range=data.salary_range,
        status=data.status,
        resume_id=data.resume_id,
        applied_at=data.applied_at,
    )
    db.add(app)
    await db.commit()
    await db.refresh(app)
    return app


async def get_application(
    db: AsyncSession, user_id: int, app_id: int
) -> JobApplication:
    """查单条求职申请，校验归属。不存在/非本人 → 抛 LookupError（API 层转 404）。"""
    result = await db.execute(
        select(JobApplication).where(
            JobApplication.id == app_id,
            JobApplication.user_id == user_id,
        )
    )
    app = result.scalar_one_or_none()
    if app is None:
        raise LookupError("求职申请不存在或无权访问")
    return app


async def list_applications(
    db: AsyncSession,
    user_id: int,
    status: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[JobApplication], int]:
    """分页查用户的求职申请列表，支持按 status 过滤。"""
    base_filter = JobApplication.user_id == user_id
    status_filter = (
        JobApplication.status == status if status is not None else None
    )

    # total
    count_stmt = select(func.count()).select_from(JobApplication).where(base_filter)
    if status_filter is not None:
        count_stmt = count_stmt.where(status_filter)
    total = (await db.execute(count_stmt)).scalar_one()

    # items
    list_stmt = (
        select(JobApplication)
        .where(base_filter)
        .order_by(JobApplication.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    if status_filter is not None:
        list_stmt = list_stmt.where(status_filter)
    items = (await db.execute(list_stmt)).scalars().all()

    return list(items), total


async def update_application(
    db: AsyncSession, user_id: int, app_id: int, data: JobApplicationUpdate
) -> JobApplication:
    """部分更新求职申请。仅更新 data 中非 None 的字段。"""
    app = await get_application(db, user_id, app_id)

    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(app, field, value)

    await db.commit()
    await db.refresh(app)
    return app


async def delete_application(
    db: AsyncSession, user_id: int, app_id: int
) -> None:
    """删除求职申请。不存在/非本人 → 抛 LookupError（API 层转 404）。"""
    app = await get_application(db, user_id, app_id)
    await db.delete(app)
    await db.commit()


async def get_kanban_stats(db: AsyncSession, user_id: int) -> dict:
    """聚合统计：按状态/公司/城市计数 + 近 30 天投递趋势。

    返回结构对齐 KanbanStatsResponse：
      {
        "by_status": {"wishlist": 3, "applied": 5, ...},
        "by_company": [{"company": "字节", "count": 2}, ...],   # top 5
        "by_city": [{"city": "北京", "count": 3}, ...],         # top 5
        "trend": [{"date": "2026-07-01", "count": 2}, ...],    # 近 30 天
        "total": 12,
      }
    """
    base_filter = JobApplication.user_id == user_id

    # ── total ──
    total = (
        await db.execute(
            select(func.count()).select_from(JobApplication).where(base_filter)
        )
    ).scalar_one()

    # ── by_status ──
    status_rows = (
        await db.execute(
            select(JobApplication.status, func.count())
            .where(base_filter)
            .group_by(JobApplication.status)
        )
    ).all()
    by_status = {row[0]: row[1] for row in status_rows}

    # ── by_company (top 5) ──
    company_rows = (
        await db.execute(
            select(JobApplication.company, func.count().label("cnt"))
            .where(base_filter)
            .group_by(JobApplication.company)
            .order_by(func.count().desc())
            .limit(5)
        )
    ).all()
    by_company = [{"company": row[0], "count": row[1]} for row in company_rows]

    # ── by_city (top 5, 排除 NULL) ──
    city_rows = (
        await db.execute(
            select(JobApplication.city, func.count().label("cnt"))
            .where(base_filter, JobApplication.city.is_not(None))
            .group_by(JobApplication.city)
            .order_by(func.count().desc())
            .limit(5)
        )
    ).all()
    by_city = [{"city": row[0], "count": row[1]} for row in city_rows]

    # ── trend (近 30 天，按日期分组) ──
    thirty_days_ago = datetime.now(timezone.utc) - timedelta(days=30)
    trend_rows = (
        await db.execute(
            select(
                func.date(JobApplication.created_at).label("d"),
                func.count().label("cnt"),
            )
            .where(base_filter, JobApplication.created_at >= thirty_days_ago)
            .group_by(func.date(JobApplication.created_at))
            .order_by(func.date(JobApplication.created_at))
        )
    ).all()
    trend = [{"date": row[0], "count": row[1]} for row in trend_rows]

    return {
        "by_status": by_status,
        "by_company": by_company,
        "by_city": by_city,
        "trend": trend,
        "total": total,
    }
