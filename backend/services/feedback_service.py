from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.qa_feedback import QAFeedback
from models.qa_history import QAHistory
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
