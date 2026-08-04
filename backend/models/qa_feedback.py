from datetime import datetime, timezone
from sqlalchemy import DateTime, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from core.database import Base


class QAFeedback(Base):
    """用户对单条问答的赞/踩反馈。

    一个 (user_id, qa_id) 只保留一条记录：允许用户改主意（切换/取消），
    重复提交为 upsert 语义，rating 以最新一次为准。
    """

    __tablename__ = "qa_feedback"
    __table_args__ = (
        UniqueConstraint("user_id", "qa_id", name="uq_qa_feedback_user_qa"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    qa_id: Mapped[int] = mapped_column(
        ForeignKey("qa_history.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    rating: Mapped[int] = mapped_column(Integer, nullable=False)  # 1 赞 / -1 踩
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
