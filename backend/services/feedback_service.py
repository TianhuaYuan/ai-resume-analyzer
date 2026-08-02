from sqlalchemy import delete, func, select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from models.feedback_like import FeedbackLike
from models.qa_feedback import QAFeedback
from models.qa_history import QAHistory
from models.user import User
from models.user_feedback import UserFeedback


# ═══════════════════════════════════════════════════════════
# QA 反馈（点赞/踩）
# ═══════════════════════════════════════════════════════════


async def submit_qa_feedback(
    db: AsyncSession,
    user_id: int,
    qa_id: int,
    rating: str,
) -> None:
    """提交问答反馈。rating: 'positive' -> 1, 'negative' -> -1。

    同一 qa_id 重复反馈时覆盖旧记录。
    抛出：
      - LookupError: qa_id 不存在（应转 404）
      - PermissionError: 存在但不属于当前用户（应转 403）
    """
    # 先查是否存在（不论归属）
    result = await db.execute(select(QAHistory).where(QAHistory.id == qa_id))
    qa = result.scalar_one_or_none()
    if qa is None:
        raise LookupError("问答记录不存在")
    if qa.user_id != user_id:
        raise PermissionError("无权访问该问答记录")

    rating_val = 1 if rating == "positive" else -1

    # 覆盖旧记录（先删后插，保证唯一性）
    await db.execute(delete(QAFeedback).where(QAFeedback.qa_id == qa_id))

    fb = QAFeedback(qa_id=qa_id, rating=rating_val)
    db.add(fb)
    await db.commit()


# ═══════════════════════════════════════════════════════════
# 用户意见箱
# ═══════════════════════════════════════════════════════════


async def submit_user_feedback(
    db: AsyncSession,
    user_id: int,
    content: str,
    feedback_type: str,
) -> UserFeedback:
    """用户提交意见箱反馈。"""
    fb = UserFeedback(
        user_id=user_id,
        content=content,
        type=feedback_type,
    )
    db.add(fb)
    await db.commit()
    await db.refresh(fb)
    return fb


async def list_user_feedback(
    db: AsyncSession,
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[UserFeedback], int]:
    """管理员分页查看意见箱。"""
    total_result = await db.execute(select(func.count()).select_from(UserFeedback))
    total = total_result.scalar_one()

    result = await db.execute(
        select(UserFeedback)
        .order_by(UserFeedback.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return result.scalars().all(), total


async def list_public_feedback(
    db: AsyncSession,
    current_user_id: int,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    """公开反馈列表：所有登录用户可看。返回 items + likes_count + is_liked。"""
    # 获取所有反馈 + 用户名 + 点赞数
    subq_likes = (
        select(
            FeedbackLike.feedback_id,
            func.count().label("likes_count"),
        )
        .group_by(FeedbackLike.feedback_id)
        .subquery()
    )

    result = await db.execute(
        select(
            UserFeedback.id,
            UserFeedback.content,
            UserFeedback.type,
            UserFeedback.status,
            UserFeedback.created_at,
            User.username.label("user_display"),
            func.coalesce(subq_likes.c.likes_count, 0).label("likes_count"),
        )
        .outerjoin(subq_likes, UserFeedback.id == subq_likes.c.feedback_id)
        .outerjoin(User, UserFeedback.user_id == User.id)
        .order_by(UserFeedback.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    rows = result.all()

    # 查询当前用户点赞过哪些 feedback
    liked_ids = set()
    if rows:
        fb_ids = [r.id for r in rows]
        liked_result = await db.execute(
            select(FeedbackLike.feedback_id).where(
                FeedbackLike.user_id == current_user_id,
                FeedbackLike.feedback_id.in_(fb_ids),
            )
        )
        liked_ids = {r[0] for r in liked_result.all()}

    return [
        {
            "id": r.id,
            "content": r.content,
            "type": r.type,
            "status": r.status,
            "created_at": r.created_at,
            "user_display": r.user_display or "匿名用户",
            "likes_count": int(r.likes_count),
            "is_liked": r.id in liked_ids,
        }
        for r in rows
    ]


async def count_public_feedback(db: AsyncSession) -> int:
    """统计公开反馈总数。"""
    result = await db.execute(select(func.count()).select_from(UserFeedback))
    return result.scalar_one()


async def toggle_feedback_like(
    db: AsyncSession,
    user_id: int,
    feedback_id: int,
) -> tuple[int, bool]:
    """点赞/取消点赞反馈。返回 (likes_count, is_liked)。"""
    # 检查 feedback 是否存在
    fb = await db.get(UserFeedback, feedback_id)
    if not fb:
        raise LookupError("反馈不存在")

    # 检查是否已点赞
    existing = await db.execute(
        select(FeedbackLike).where(
            FeedbackLike.user_id == user_id,
            FeedbackLike.feedback_id == feedback_id,
        )
    )
    like = existing.scalar_one_or_none()

    if like:
        await db.delete(like)
        is_liked = False
    else:
        db.add(FeedbackLike(user_id=user_id, feedback_id=feedback_id))
        is_liked = True

    await db.commit()

    # 获取当前点赞数
    count_result = await db.execute(
        select(func.count()).select_from(FeedbackLike).where(
            FeedbackLike.feedback_id == feedback_id
        )
    )
    likes_count = count_result.scalar_one()

    return likes_count, is_liked
