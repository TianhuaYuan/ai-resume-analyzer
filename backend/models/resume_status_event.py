"""简历状态流转事件（fieldwork fw_events + setStatus 对照）。

fieldwork 的 setStatus 一次调用 = 更新状态 + 插入 status_change 事件（from → to）。
本表记录简历每次状态迁移（processing/ready/failed/draft），供失败复盘、卡死诊断、
前端时间线展示。
"""

from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base


class ResumeStatusEvent(Base):
    """简历状态迁移事件（ADD-only，不修改不删除）。"""

    __tablename__ = "resume_status_events"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    resume_id: Mapped[int] = mapped_column(
        ForeignKey("resumes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    from_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    to_status: Mapped[str] = mapped_column(String(20), nullable=False)
    # 迁移原因载体（如失败消息），对齐 fieldwork status_change 事件的 reason 语义
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
