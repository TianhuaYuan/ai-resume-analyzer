from datetime import datetime, timezone

from sqlalchemy import case, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.feedback_like import FeedbackLike
from models.qa_feedback import QAFeedback
from models.qa_history import QAHistory
from models.resume import Resume
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
    """提交问答反馈（upsert 语义）。rating: 'positive' -> 1, 'negative' -> -1。

    同一 (user_id, qa_id) 重复提交时更新 rating，不产生重复行，允许用户改主意。
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
    now = datetime.now(timezone.utc)

    # upsert：同 (user_id, qa_id) 只保留一条
    existing = await db.execute(
        select(QAFeedback).where(
            QAFeedback.user_id == user_id,
            QAFeedback.qa_id == qa_id,
        )
    )
    row = existing.scalar_one_or_none()
    if row:
        row.rating = rating_val
        row.updated_at = now
    else:
        db.add(QAFeedback(user_id=user_id, qa_id=qa_id, rating=rating_val))
    await db.commit()


async def cancel_qa_feedback(
    db: AsyncSession,
    user_id: int,
    qa_id: int,
) -> bool:
    """取消对某条问答的反馈（点同按钮再点一次即取消）。

    不存在或非本人时返回 False（不报错，幂等）。
    """
    result = await db.execute(
        delete(QAFeedback).where(
            QAFeedback.user_id == user_id,
            QAFeedback.qa_id == qa_id,
        )
    )
    await db.commit()
    return result.rowcount > 0


async def qa_feedback_stats(
    db: AsyncSession,
    top_resumes: int = 10,
    recent_negative: int = 5,
) -> dict:
    """QA 反馈统计（管理员用）。

    返回：
      - 总体正/负/负向率
      - 按简历聚合的负向率排行（定位哪份简历的问答质量差）
      - 最近 negative 样本（问题 + 答案截断 + process_trace），用于复盘回答短板
    """
    total_result = await db.execute(select(func.count()).select_from(QAFeedback))
    total = total_result.scalar_one()

    pos_result = await db.execute(
        select(func.count())
        .select_from(QAFeedback)
        .where(QAFeedback.rating == 1)
    )
    positive = pos_result.scalar_one()

    neg_result = await db.execute(
        select(func.count())
        .select_from(QAFeedback)
        .where(QAFeedback.rating == -1)
    )
    negative = neg_result.scalar_one()

    negative_rate = round(negative / total, 4) if total else 0.0

    # 按简历聚合正负计数
    by_resume_result = await db.execute(
        select(
            QAHistory.resume_id,
            Resume.filename.label("resume_title"),
            func.coalesce(
                func.sum(case((QAFeedback.rating == 1, 1), else_=0)), 0
            ).label("positive"),
            func.coalesce(
                func.sum(case((QAFeedback.rating == -1, 1), else_=0)), 0
            ).label("negative"),
        )
        .join(QAFeedback, QAFeedback.qa_id == QAHistory.id)
        .outerjoin(Resume, QAHistory.resume_id == Resume.id)
        .group_by(QAHistory.resume_id, Resume.filename)
        .order_by(
            func.sum(case((QAFeedback.rating == -1, 1), else_=0)).desc()
        )
        .limit(top_resumes)
    )
    by_resume = []
    for r in by_resume_result.all():
        pos, neg = int(r.positive), int(r.negative)
        by_resume.append(
            {
                "resume_id": r.resume_id,
                "resume_title": r.resume_title or f"简历#{r.resume_id}",
                "positive": pos,
                "negative": neg,
                "negative_rate": round(neg / (pos + neg), 4) if (pos + neg) else 0.0,
            }
        )

    # 最近 negative 样本（带 process_trace 便于定位回答短板）
    recent_result = await db.execute(
        select(QAHistory, QAFeedback.created_at)
        .join(QAFeedback, QAFeedback.qa_id == QAHistory.id)
        .where(QAFeedback.rating == -1)
        .order_by(QAFeedback.created_at.desc())
        .limit(recent_negative)
    )
    recent_negative_samples = [
        {
            "qa_id": qa.id,
            "question": qa.question,
            "answer_excerpt": (qa.answer or "")[:200],
            "resume_id": qa.resume_id,
            "created_at": fb_created,
            "process_trace": qa.process_trace,
        }
        for qa, fb_created in recent_result.all()
    ]

    return {
        "total_feedback": total,
        "positive": positive,
        "negative": negative,
        "negative_rate": negative_rate,
        "by_resume": by_resume,
        "recent_negative": recent_negative_samples,
    }


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
