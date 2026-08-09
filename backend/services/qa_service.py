import logging
from datetime import datetime, timezone

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from models.qa_history import QAHistory
from models.qa_conversation import QAConversation

logger = logging.getLogger(__name__)


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


async def mark_qa_interrupted(
    db: AsyncSession, qa_id: int, answer: str | None = None
) -> None:
    """标记中断/失败的 QA 记录为 failed，避免 status=streaming 空记录污染历史。

    Args:
        answer: 可选失败原因文本（写入 answer 字段，供前端展示「重试」入口）。
    """
    values: dict = {"status": "failed"}
    if answer is not None:
        values["answer"] = answer
    await db.execute(
        update(QAHistory)
        .where(QAHistory.id == qa_id, QAHistory.status == "streaming")
        .values(**values)
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


# ── 问答 → L4 长期记忆回流（问答画像） ──────────────────

# 拒答话术：检索不到信息时的固定回答（rag/pipeline.py + agentic_rag/generate.py），
# 这类回答不含用户信息，不应沉淀为画像。
_QA_REJECT_PHRASES = ("抱歉，简历中未提及该信息。", "分析失败，请稍后重试")
# 有信息量问答的最小答案长度（字符）：短回答多为寒暄/确认/无实质内容，不沉淀。
QA_MEMORY_MIN_ANSWER_LEN = 80
# 问答沉淀的重要度：适中（面试复盘 importance=0.7，问答画像略低）
QA_MEMORY_IMPORTANCE = 0.55
# snippet 中 question / answer 的最大长度（防向量稀释 + 噪音）
_QA_MEMORY_Q_LEN = 30
_QA_MEMORY_A_LEN = 200


def _truncate(text: str, n: int) -> str:
    text = (text or "").strip()
    return text if len(text) <= n else text[:n] + "…"


def _looks_like_rejection(answer: str) -> bool:
    """命中拒答话术（如"抱歉，简历中未提及该信息。"）→ 不含用户信息。"""
    a = answer.strip()
    return any(a.startswith(p) for p in _QA_REJECT_PHRASES)


def is_informative_qa(question: str, answer: str) -> bool:
    """筛选"有信息量"的问答：非拒答话术 + 答案超过长度阈值。

    对齐 mem0 / graphiti 的沉淀思路（内容空洞的发言不值得记忆）：
    拒答话术 ≈ 无实质内容的应答，短答案 ≈ 寒暄/确认，都不沉淀；
    只有暴露用户信息的实质问答才回流到 L4 画像。
    """
    q = (question or "").strip()
    a = (answer or "").strip()
    if not q or not a:
        return False
    if _looks_like_rejection(a):
        return False
    return len(a) >= QA_MEMORY_MIN_ANSWER_LEN


async def save_qa_to_memory(
    *,
    user_id: int,
    question: str,
    answer: str,
) -> bool:
    """把有信息量的问答沉淀到 L4 长期记忆（问答 → 用户画像回流）。

    筛选：is_informative_qa 命中（非拒答 + 答案足够长）才写。
    snippet 形式 ``问答沉淀（{问题前30}）：{答案前200}``，memory_type=semantic，
    importance=0.55（面试复盘 0.7 之下，适中）。
    幂等：save_memory 按 snippet hash 去重覆盖，同一问答不重复沉淀。

    Returns: 是否成功沉淀。内部 try/except 保证失败不阻断问答主流程
    （同 interview_service.update_scorecard 的"记忆是增强信息"约定）。
    """
    if not is_informative_qa(question, answer):
        return False
    key = _truncate(question, _QA_MEMORY_Q_LEN)
    try:
        from services.memory.memory_store import save_memory

        await save_memory(
            user_id=user_id,
            snippet=f"问答沉淀（{key}）：{_truncate(answer, _QA_MEMORY_A_LEN)}",
            memory_type="semantic",
            importance=QA_MEMORY_IMPORTANCE,
        )
        return True
    except Exception:
        logger.warning("问答沉淀 L4 记忆失败 user_id=%s question=%s", user_id, key, exc_info=True)
        return False
