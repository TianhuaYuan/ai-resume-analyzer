from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_current_user, require_admin
from core.database import get_db
from core.limiter import limiter
from models.user import User
from schemas.feedback import (
    LikeResponse,
    PublicFeedbackItem,
    PublicFeedbackListResponse,
    UserFeedbackListResponse,
    UserFeedbackRequest,
    UserFeedbackItem,
)
from services.feedback_service import (
    count_public_feedback,
    list_public_feedback,
    list_user_feedback,
    submit_user_feedback,
    toggle_feedback_like,
)

router = APIRouter(prefix="/feedback", tags=["feedback"])


@router.post("", status_code=status.HTTP_201_CREATED)
@limiter.limit("10/minute")
async def create_user_feedback(
    request: Request,
    data: UserFeedbackRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """用户提交意见箱反馈。

    限流 10 条/分钟，防止刷反馈。
    """
    fb = await submit_user_feedback(
        db,
        user_id=current_user.id,
        content=data.content,
        feedback_type=data.type,
    )
    return {"id": fb.id, "detail": "反馈已提交，感谢你的建议"}


@router.get("", response_model=UserFeedbackListResponse)
async def get_user_feedback_list(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    """管理员分页查看意见箱反馈。

    仅 settings.ADMIN_EMAILS 中的用户可访问。
    """
    items, total = await list_user_feedback(db, limit=limit, offset=offset)
    return UserFeedbackListResponse(
        items=[UserFeedbackItem.model_validate(it) for it in items],
        total=total,
    )


# ── 公开接口（所有登录用户可访问） ──────────────────────


@router.get("/public", response_model=PublicFeedbackListResponse)
async def get_public_feedback_list(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """公开反馈列表 — 所有登录用户可看。返回用户名 + 点赞数 + 是否已点赞。"""
    items = await list_public_feedback(db, current_user.id, limit=limit, offset=offset)
    total = await count_public_feedback(db)
    return PublicFeedbackListResponse(
        items=[PublicFeedbackItem(**item) for item in items],
        total=total,
    )


@router.post("/public/{fb_id}/like", response_model=LikeResponse)
async def like_feedback(
    fb_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """点赞/取消点赞反馈（toggle）。"""
    try:
        likes_count, is_liked = await toggle_feedback_like(db, current_user.id, fb_id)
    except LookupError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="反馈不存在",
        )
    return LikeResponse(likes_count=likes_count, is_liked=is_liked)
