"""E2: 简历改写 → 字段级 diff 审阅队列（PendingChange 存储模型）。"""

from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base


class PendingChange(Base):
    """改写类工具产生的字段级改动记录（E2）。

    改写工具（rewrite_star / translate / rewrite_resume）落库后，
    由 diff 计算函数生成字段级 PendingChange 行，前端逐条接受/丢弃：
    - status=pending：待用户审阅
    - status=accepted：用户确认保留（AI 改动已生效）
    - status=rejected：用户丢弃（字段已按 before 还原）

    field_path 采用点号路径，items 按条目 id 寻址：
      - 平铺字段：  "summary" / "name"
      - 条目字段：  "items.<item_id>.description"
      - 新增/删除条目： "items.<item_id>"（before/after 其一为 None）
    """

    __tablename__ = "pending_changes"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    resume_id: Mapped[int] = mapped_column(
        ForeignKey("resumes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tool_name: Mapped[str] = mapped_column(String(50), nullable=False)
    module_type: Mapped[str] = mapped_column(String(50), nullable=False)
    # 点号路径：items.<item_id>.field / 平铺 field / items.<item_id>
    field_path: Mapped[str] = mapped_column(String(255), nullable=False)
    before: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    after: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    rationale: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), default="pending", server_default="pending", nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
