"""投递状态机（J 功能，third_party/Job recruit.py STATUS_FLOW 对照，阶段 5）。

投递追踪：公司/岗位/链接/状态/优先级/截止/备注 + timeline 时间线 JSON +
软删除垃圾箱（deleted_at）。JD 评分卡（jd_scorecard）+ match_keys 去重。

timeline 形状（列表，状态流转自动追加）：
    [{"at": "2026-08-06T12:00:00Z", "from": "待投递", "to": "已投递", "note": "..."}]

jd_scorecard 形状（fieldwork JD 评分卡对照）：
    {"grade": "B", "comp_min": 15, "comp_max": 25,
     "pain_line": "……", "gaps": ["……"], "generated_at": "ISO"}
"""

from datetime import date, datetime, timezone

from sqlalchemy import JSON, Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base


class JobApplication(Base):
    """一条投递记录（软删除）。"""

    __tablename__ = "job_applications"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    company: Mapped[str] = mapped_column(String(120), nullable=False)
    position: Mapped[str] = mapped_column(String(120), nullable=False)
    url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # 待投递/已投递/笔试/一面/二面/三面/HR面/Offer/已拒
    status: Mapped[str] = mapped_column(String(20), default="待投递", nullable=False, index=True)
    # 高/中/低
    priority: Mapped[str] = mapped_column(String(10), default="中", nullable=False)
    deadline: Mapped[date | None] = mapped_column(Date, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    jd_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    jd_scorecard: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # 去重键（JSON 字符串列表）：company+position 归一 + 归一化 URL
    match_keys: Mapped[list | None] = mapped_column(JSON, nullable=True)
    normalized_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # 时间线（JSON 列表，状态流转自动追加）
    timeline: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # 软删除时间戳：非空 = 已进垃圾箱
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
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
