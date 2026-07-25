from datetime import datetime, timezone
from sqlalchemy import String, Text, Integer, ForeignKey, DateTime, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from core.database import Base


class Resume(Base):
    __tablename__ = "resumes"
    # P1-9: (user_id, idempotency_key) 复合唯一约束，DB 层兜底并发竞态
    # 与 alembic/versions/003_add_unique_constraint_resume_user_idempotency.py 保持一致
    __table_args__ = (
        UniqueConstraint("user_id", "idempotency_key", name="uq_resume_user_idempotency"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    file_path: Mapped[str] = mapped_column(String(512), nullable=False)
    parsed_text: Mapped[str] = mapped_column(Text, nullable=False)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(
        String(20), default="processing"
    )  # processing / ready / failed
    status_message: Mapped[str] = mapped_column(String(255), default="")
    # 幂等上传键：由客户端在 Idempotency-Key 头提供，按用户维度去重（普通索引列，业务层判重）
    idempotency_key: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
