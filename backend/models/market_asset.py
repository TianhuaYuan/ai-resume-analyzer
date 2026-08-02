"""市场资产表（公共数据，所有用户共享）。

承载从爬虫 JSON 同步进来的求职市场数据：岗位 JD、简历范文、求职攻略。
与 knowledge_assets（每用户私有资产）分离——本表无 user_id，是公共资产。

结构化字段（company/position/salary/city/job_type 等）供筛选/统计/分页，
content 是全文唯一载体（D2 脏标记模式，同 resumes/knowledge_assets），
向量索引进 Chroma 公共集合 market_public（所有用户共享一份）。
"""

from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base


class MarketAsset(Base):
    __tablename__ = "market_assets"
    __table_args__ = (
        UniqueConstraint("source", "external_id", name="uq_market_source_external"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    # 数据管道来源：campus / jd / social / sample / guide
    source: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    # 源 JSON 原始 id（幂等 upsert 唯一键）
    external_id: Mapped[str] = mapped_column(String(100), nullable=False)
    # RAG metadata 用资产类型：job / sample / guide
    asset_type: Mapped[str] = mapped_column(String(20), nullable=False)
    # 仅 job 资产：campus / social / intern
    job_type: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    company: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    position: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    city: Mapped[str | None] = mapped_column(String(255), nullable=True)  # 可逗号分隔多城市
    industry: Mapped[str | None] = mapped_column(String(255), nullable=True)
    salary: Mapped[str | None] = mapped_column(String(100), nullable=True)
    degree: Mapped[str | None] = mapped_column(String(100), nullable=True)  # 学历要求
    deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_expired: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    # sample: {style, modules, target_position}；guide: {tags}
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # 全文（D2 脏标记唯一载体）
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    indexed_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_published: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
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
