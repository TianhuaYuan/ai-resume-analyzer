"""管理员后台 API。

所有端点均需 require_admin 依赖（settings.ADMIN_EMAILS 中的邮箱才放行）。
提供：审计日志、用户列表、系统统计、意见箱反馈、模板列表。
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import require_admin
from core.database import get_db
from models.user import User
from schemas.admin import (
    AdminUserItem,
    AdminUserListResponse,
    AuditLogListResponse,
    AuditLogResponse,
    SystemStatsResponse,
    TemplateInfoResponse,
    TemplateListResponse,
)
from schemas.feedback import UserFeedbackItem, UserFeedbackListResponse
from services.admin_service import (
    get_system_stats,
    list_all_users,
    list_audit_logs,
    list_templates,
)
from services.feedback_service import list_user_feedback

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/audit-logs", response_model=AuditLogListResponse)
async def get_audit_logs(
    action: str | None = Query(None, description="按操作类型过滤"),
    user_id: int | None = Query(None, description="按用户 ID 过滤"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    """分页查询审计日志，支持 action / user_id 过滤。"""
    items, total = await list_audit_logs(
        db, action=action, user_id=user_id, limit=limit, offset=offset
    )
    return AuditLogListResponse(
        items=[AuditLogResponse.model_validate(it) for it in items],
        total=total,
    )


@router.get("/users", response_model=AdminUserListResponse)
async def get_users(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    """分页查询用户列表（仅 id/username/email/created_at）。"""
    items, total = await list_all_users(db, limit=limit, offset=offset)
    return AdminUserListResponse(
        items=[AdminUserItem.model_validate(it) for it in items],
        total=total,
    )


@router.get("/stats", response_model=SystemStatsResponse)
async def get_stats(
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    """系统级统计数据。"""
    return SystemStatsResponse(**await get_system_stats(db))


@router.get("/feedback", response_model=UserFeedbackListResponse)
async def get_admin_feedback(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    """管理员查看意见箱反馈（与 /api/v1/feedback 等价，聚合到 admin 命名空间）。"""
    items, total = await list_user_feedback(db, limit=limit, offset=offset)
    return UserFeedbackListResponse(
        items=[UserFeedbackItem.model_validate(it) for it in items],
        total=total,
    )


@router.get("/templates", response_model=TemplateListResponse)
async def get_templates(
    _admin: User = Depends(require_admin),
):
    """列出可用简历模板。"""
    return TemplateListResponse(
        templates=[TemplateInfoResponse(**t) for t in list_templates()]
    )
