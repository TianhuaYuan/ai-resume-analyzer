"""T37: 产品分析事件模型。

记录用户在产品中的关键行为（注册/上传/构建/导出等），
支持 CTA 来源渠道（source）与附加上下文（metadata）追踪，
供管理员后台做漏斗分析（GET /analytics/funnel）。
"""

from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base


class AnalyticsEvent(Base):
    __tablename__ = "analytics_events"
    __table_args__ = (
        # 漏斗查询按 created_at 过滤 + event_name 分组，联合索引加速
        Index("ix_analytics_events_name_time", "event_name", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    # 用户删除时事件保留（SET NULL），漏斗分析仍需历史事件
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    event_name: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    # CTA 渠道，如 ?source=linkedin
    source: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # 附加上下文（JSON），如 {format: "pdf"}。
    # 注意：SQLAlchemy Declarative 保留类属性名 "metadata"，故属性名用 event_metadata，
    # 通过显式列名 "metadata" 保持 DB 表结构与需求一致。
    event_metadata: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
