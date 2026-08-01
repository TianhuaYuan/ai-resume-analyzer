from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_current_user, require_admin
from core.database import get_db
from core.limiter import limiter
from models.user import User
from schemas.feedback import UserFeedbackListResponse, UserFeedbackRequest, UserFeedbackItem
from services.feedback_service import list_user_feedback, submit_user_feedback

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
