from datetime import datetime, timezone

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from models.qa_history import QAHistory
from models.qa_conversation import QAConversation


# ── 问答记录（已有函数 + conversation_id 参数） ────────────

async def save_qa(
    db: AsyncSession,
    user_id: int,
    resume_id: int,
    question: str,
    answer: str,
    sources: list[dict],
    token_usage: int = 0,
    conversation_id: int | None = None,
) -> QAHistory:
    record = QAHistory(
        user_id=user_id,
        resume_id=resume_id,
        question=question,
        answer=answer,
        sources=sources,
        token_usage=token_usage,
        conversation_id=conversation_id,
    )
    db.add(record)

    # 有新问答时刷新对应对话的 updated_at
    if conversation_id is not None:
        await db.execute(
            update(QAConversation)
            .where(
                QAConversation.id == conversation_id,
                QAConversation.user_id == user_id,
            )
            .values(updated_at=datetime.now(timezone.utc))
        )

    await db.commit()
    await db.refresh(record)
    return record


async def mark_qa_interrupted(db: AsyncSession, qa_id: int) -> None:
    """标记中断的 QA 记录（会话断连）为 failed，避免 status=streaming 空记录污染历史。"""
    await db.execute(
        update(QAHistory)
        .where(QAHistory.id == qa_id, QAHistory.status == "streaming")
        .values(status="failed")
    )
    await db.commit()


async def get_history(
    db: AsyncSession,
    user_id: int,
    resume_id: int,
    limit: int = 20,
    offset: int = 0,
    keyword: str | None = None,
    conversation_id: int | None = None,
) -> tuple[list[QAHistory], int]:
    """分页查某份简历（可选某对话）的问答历史。

    keyword 非空时，在 question / answer 上做 ilike 模糊匹配。
    conversation_id 非空时，只查该对话下的问答。
    """
    base_filters = [QAHistory.user_id == user_id, QAHistory.resume_id == resume_id]
    # 只显示已完成的问答（过滤 streaming/failed 等未完成记录，避免中断空记录污染历史）
    base_filters.append(QAHistory.status == "complete")

    if keyword:
        pattern = f"%{keyword}%"
        base_filters.append(
            or_(
                QAHistory.question.ilike(pattern),
                QAHistory.answer.ilike(pattern),
            )
        )

    if conversation_id is not None:
        base_filters.append(QAHistory.conversation_id == conversation_id)

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
    conversation_id: int | None = None,
) -> int:
    """清空指定简历（或指定对话）的问答历史。"""
    filters = [QAHistory.user_id == user_id, QAHistory.resume_id == resume_id]
    if conversation_id is not None:
        filters.append(QAHistory.conversation_id == conversation_id)

    count_result = await db.execute(
        select(func.count()).select_from(QAHistory).where(*filters)
    )
    count = count_result.scalar_one()

    await db.execute(delete(QAHistory).where(*filters))
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


# ── 对话会话 CRUD ────────────────────────────────────────


async def create_conversation(
    db: AsyncSession,
    user_id: int,
    resume_id: int,
    title: str | None = None,
) -> QAConversation:
    """创建新对话。title 为 None 时默认"新对话"。"""
    conv = QAConversation(
        user_id=user_id,
        resume_id=resume_id,
        title=title or "新对话",
    )
    db.add(conv)
    await db.commit()
    await db.refresh(conv)
    return conv


async def get_conversations(
    db: AsyncSession,
    user_id: int,
    resume_id: int,
) -> list[QAConversation]:
    """列出某简历下所有对话，附带各对话的消息数，按 updated_at 降序。"""
    result = await db.execute(
        select(QAConversation)
        .where(
            QAConversation.user_id == user_id,
            QAConversation.resume_id == resume_id,
        )
        .order_by(QAConversation.updated_at.desc())
    )
    return result.scalars().all()


async def get_conversation_message_count(
    db: AsyncSession,
    conversation_id: int,
) -> int:
    """获取指定对话的问答消息数。"""
    result = await db.execute(
        select(func.count())
        .select_from(QAHistory)
        .where(QAHistory.conversation_id == conversation_id)
    )
    return result.scalar_one()


async def rename_conversation(
    db: AsyncSession,
    user_id: int,
    conversation_id: int,
    title: str,
) -> QAConversation | None:
    """重命名对话。返回更新后的对象，不存在或非本人时返回 None。"""
    result = await db.execute(
        update(QAConversation)
        .where(
            QAConversation.id == conversation_id,
            QAConversation.user_id == user_id,
        )
        .values(title=title, updated_at=datetime.now(timezone.utc))
    )
    await db.commit()
    if result.rowcount == 0:
        return None
    # 重新查询返回更新后的对象
    conv_result = await db.execute(
        select(QAConversation).where(QAConversation.id == conversation_id)
    )
    return conv_result.scalar_one_or_none()


async def delete_conversation(
    db: AsyncSession,
    user_id: int,
    conversation_id: int,
) -> int | None:
    """删除对话及其所有问答。返回被删除的问答数，不存在或非本人时返回 None。

    先清关联的 qa_history（SET NULL），再统计并删除它们，最后删对话本身。
    """
    # 校验归属
    conv_result = await db.execute(
        select(QAConversation).where(
            QAConversation.id == conversation_id,
            QAConversation.user_id == user_id,
        )
    )
    conv = conv_result.scalar_one_or_none()
    if conv is None:
        return None

    # 统计该对话下的问答数
    count_result = await db.execute(
        select(func.count())
        .select_from(QAHistory)
        .where(QAHistory.conversation_id == conversation_id)
    )
    qa_count = count_result.scalar_one()

    # 删除问答（SET NULL 由 FK ondelete 处理，但显式删除更干净）
    await db.execute(
        delete(QAHistory).where(QAHistory.conversation_id == conversation_id)
    )

    # 删除对话
    await db.execute(
        delete(QAConversation).where(QAConversation.id == conversation_id)
    )
    await db.commit()
    return qa_count
