from datetime import datetime, timezone
from sqlalchemy import DateTime, JSON, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from core.database import Base


class ResumeModule(Base):
    __tablename__ = "resume_modules"
    __table_args__ = (
        UniqueConstraint("resume_id", "module_type", name="uq_resume_module"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    resume_id: Mapped[int] = mapped_column(
        ForeignKey("resumes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    module_type: Mapped[str] = mapped_column(String(50), nullable=False)
    content: Mapped[dict] = mapped_column(JSON, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # G 可信度控制：fact/inferred/mixed（AI 改写内容来源标注）
    source: Mapped[str] = mapped_column(
        String(20), default="fact", server_default="fact", nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
