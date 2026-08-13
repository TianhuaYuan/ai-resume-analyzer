"""通用知识资产表。

承载 resume 之外的求职知识资产：JD、面试记录、笔记等。
与 resumes 表遵循同一套"内容哈希 + 索引哈希"脏标记模式（D2），
检索层统一按 (asset_type, asset_id) 对待，不分表。
"""

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base


class KnowledgeAsset(Base):
    __tablename__ = "knowledge_assets"

    # 归档幂等：同一业务来源（投递/面试）最多一条资产；手动 note 资产 source 为 NULL
    __table_args__ = (
        UniqueConstraint(
            "user_id", "source_type", "source_id", name="uq_knowledge_assets_source"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # jd / interview / note（resume 复用 resumes 表，不在此）
    asset_type: Mapped[str] = mapped_column(String(20), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    # 资产源文本（唯一内容载体，索引与整文直读都从这里取）
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # (D2)：脏标记模式，同 resumes
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    indexed_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # 草稿中间态：is_draft=True 只进工作区，不触发索引（D3）
    is_draft: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    # 归档来源：业务表 → 知识资产的溯源（job_application / interview_session）。
    # 手动新建的 note 资产为 NULL；来源相同则归档幂等（upsert 覆盖）。
    source_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    source_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # 向量索引版本号（单调递增，独立于 document version）
    index_version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
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
