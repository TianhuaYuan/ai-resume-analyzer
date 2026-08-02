from datetime import datetime, timezone
from sqlalchemy import DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from core.database import Base


class FeedbackLike(Base):
    """用户对反馈的点赞。"""

    __tablename__ = "feedback_likes"
    __table_args__ = (
        UniqueConstraint("user_id", "feedback_id", name="uq_feedback_like_user_feedback"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    feedback_id: Mapped[int] = mapped_column(
        ForeignKey("user_feedback.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
