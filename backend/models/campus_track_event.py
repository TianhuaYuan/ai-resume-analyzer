"""校招求职状态流转事件（ADD-only，对齐 resume_status_events + fieldwork fw_events）。

每次状态变更（PUT /campus/tracks）在事务内追加一条，供求职复盘（compute_reached 阶段阶梯、
ghost 判定、回响天数）与前端时间线使用。只增不改不删。

事件类型（event_type）：
  - applied        用户投递
  - status_change  状态流转（from → to，PUT 端点的常规写入）
  - rejection      收到拒信
  - interview      面试发生（可带 to_status 标明轮次）
  - note           普通备注（不证明到达任何阶段）
"""

from datetime import date, datetime, timezone

from sqlalchemy import Date, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base


class CampusTrackEvent(Base):
    """校招求职跟踪事件（ADD-only，不修改不删除）。"""

    __tablename__ = "campus_track_events"
    __table_args__ = (
        Index("ix_campus_track_events_user_record", "user_id", "campus_record_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    campus_record_id: Mapped[str] = mapped_column(String(100), nullable=False)
    event_type: Mapped[str] = mapped_column(String(30), nullable=False)
    from_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    to_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 事件发生的业务日期（默认今天）；未来日期的 interview 事件用于 ghost 阻断
    occurred_at: Mapped[date] = mapped_column(
        Date,
        default=lambda: date.today(),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
