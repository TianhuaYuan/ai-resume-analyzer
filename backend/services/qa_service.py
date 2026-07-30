from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.qa_history import QAHistory


async def save_qa(
    db: AsyncSession,
    user_id: int,
    resume_id: int,
    question: str,
    answer: str,
    sources: list[dict],
    token_usage: int = 0,
) -> QAHistory:
    record = QAHistory(
        user_id=user_id,
        resume_id=resume_id,
        question=question,
        answer=answer,
        sources=sources,
        token_usage=token_usage,
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
    keyword: str | None = None,
) -> tuple[list[QAHistory], int]:
    """分页查某份简历的问答历史。

    keyword 非空时，在 question / answer 上做 ilike 模糊匹配。
    SQL 参数化，无注入风险；keyword 前后通配符 % 由 SQLAlchemy 处理。
    """
    base_filters = [QAHistory.user_id == user_id, QAHistory.resume_id == resume_id]

    if keyword:
        pattern = f"%{keyword}%"
        base_filters.append(
            or_(
                QAHistory.question.ilike(pattern),
                QAHistory.answer.ilike(pattern),
            )
        )

    total_result = await db.execute(
        select(func.count()).select_from(QAHistory).where(*base_filters)
    )
    total = total_result.scalar_one()

    result = await db.execute(
        select(QAHistory)
        .where(*base_filters)
        .order_by(QAHistory.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return result.scalars().all(), total


async def delete_history_by_resume(
    db: AsyncSession,
    user_id: int,
    resume_id: int,
) -> int:
    """清空指定用户指定简历的所有问答历史。"""
    count_result = await db.execute(
        select(func.count())
        .select_from(QAHistory)
        .where(QAHistory.user_id == user_id, QAHistory.resume_id == resume_id)
    )
    count = count_result.scalar_one()

    await db.execute(
        delete(QAHistory).where(QAHistory.user_id == user_id, QAHistory.resume_id == resume_id)
    )
    await db.commit()
    return count


async def delete_qa_by_id(
    db: AsyncSession,
    user_id: int,
    qa_id: int,
) -> bool:
    """删单条问答。user_id 隔离。"""
    result = await db.execute(
        delete(QAHistory).where(QAHistory.id == qa_id, QAHistory.user_id == user_id)
    )
    await db.commit()
    return result.rowcount > 0
