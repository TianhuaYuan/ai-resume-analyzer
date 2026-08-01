"""T33: 求职申请（Job Application）API 路由。

看板 CRUD + 聚合统计，所有接口均需认证并做 user_id 归属隔离。

路由顺序注意：/jobs/kanban 必须在 /jobs/{app_id} 之前注册，
否则 "kanban" 会被当作 {app_id} 路径参数匹配（int 转换失败 → 422）。
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_current_user
from core.database import get_db
from models.user import User
from schemas.job_application import (
    JobApplicationCreate,
    JobApplicationListResponse,
    JobApplicationResponse,
    JobApplicationUpdate,
    KanbanStatsResponse,
)
from services.job_application_service import (
    create_application,
    delete_application,
    get_application,
    get_kanban_stats,
    list_applications,
    update_application,
)

router = APIRouter(prefix="/jobs", tags=["job-applications"])


@router.post("", response_model=JobApplicationResponse, status_code=status.HTTP_201_CREATED)
async def create_job_application(
    data: JobApplicationCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """创建一条求职申请。"""
    app = await create_application(db, current_user.id, data)
    return app


@router.get("", response_model=JobApplicationListResponse)
async def list_job_applications(
    status_filter: str | None = Query(default=None, alias="status", description="按状态过滤"),
    limit: int = Query(20, ge=1, le=100, description="每页数量 1-100"),
    offset: int = Query(0, ge=0, description="偏移量 >=0"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """分页查求职申请列表，支持按 status 过滤。"""
    items, total = await list_applications(
        db, current_user.id, status=status_filter, limit=limit, offset=offset
    )
    return JobApplicationListResponse(
        items=[JobApplicationResponse.model_validate(it) for it in items],
        total=total,
    )


@router.get("/kanban", response_model=KanbanStatsResponse)
async def get_kanban(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """看板聚合统计：按状态/公司/城市计数 + 近 30 天投递趋势。

    供前端 recharts 图表直接消费。
    """
    return await get_kanban_stats(db, current_user.id)


@router.get("/{app_id}", response_model=JobApplicationResponse)
async def get_job_application(
    app_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """查单条求职申请。不存在/非本人 → 404。"""
    try:
        app = await get_application(db, current_user.id, app_id)
    except LookupError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="求职申请不存在或无权访问",
        )
    return app


@router.put("/{app_id}", response_model=JobApplicationResponse)
async def update_job_application(
    app_id: int,
    data: JobApplicationUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """部分更新求职申请。仅更新传入的字段。"""
    try:
        app = await update_application(db, current_user.id, app_id, data)
    except LookupError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="求职申请不存在或无权访问",
        )
    return app


@router.delete("/{app_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_job_application(
    app_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """删除求职申请。不存在/非本人 → 404。"""
    try:
        await delete_application(db, current_user.id, app_id)
    except LookupError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="求职申请不存在或无权访问",
        )
    return None
