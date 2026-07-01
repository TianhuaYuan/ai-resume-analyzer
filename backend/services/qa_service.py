from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.qa_history import QAHistory


async def save_qa(
    db: AsyncSession,
    user_id: int,
    resume_id: int,
    question: str,
    answer: str,
    sources: list[dict],
) -> QAHistory:
    record = QAHistory(
        user_id=user_id,
        resume_id=resume_id,
        question=question,
        answer=answer,
        sources=sources,
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)
    return record


async def get_history(
    db: AsyncSession,
    user_id: int,
    resume_id: int,
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[QAHistory], int]:
    """分页查某份简历的问答历史"""
    total_result = await db.execute(
        select(func.count())
        .select_from(QAHistory)
        .where(QAHistory.user_id == user_id, QAHistory.resume_id == resume_id)
    )
    total = total_result.scalar_one()
    result = await db.execute(
        select(QAHistory)
        .where(QAHistory.user_id == user_id, QAHistory.resume_id == resume_id)
        .order_by(QAHistory.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return result.scalars().all(), total
