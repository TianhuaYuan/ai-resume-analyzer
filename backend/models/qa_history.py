from datetime import datetime, timezone
from sqlalchemy import Integer, Text, JSON, ForeignKey, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column
from core.database import Base


class QAHistory(Base):
    __tablename__ = "qa_history"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    resume_id: Mapped[int] = mapped_column(
        ForeignKey("resumes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    sources: Mapped[list] = mapped_column(JSON, nullable=True)
    # 行 459: DB 存完整 prompt（system + 记忆注入 + 工具序列 + 模型）
    process_trace: Mapped[dict] = mapped_column(JSON, nullable=True)
    # S1 T1: SSE 流中占位状态
    status: Mapped[str] = mapped_column(
        String(20), default="complete", nullable=False
    )
    conversation_id: Mapped[int | None] = mapped_column(
        ForeignKey("qa_conversations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    token_usage: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
