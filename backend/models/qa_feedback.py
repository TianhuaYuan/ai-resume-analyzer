from datetime import datetime, timezone
from sqlalchemy import DateTime, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column
from core.database import Base


class QAFeedback(Base):
    __tablename__ = "qa_feedback"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    qa_id: Mapped[int] = mapped_column(
        ForeignKey("qa_history.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    rating: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
