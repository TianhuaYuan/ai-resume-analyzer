"""市场岗位表（公共数据，所有用户共享）。

承载从爬虫 JSON 同步进来的求职岗位数据（校招/社招/实习）。
与 knowledge_assets（每用户私有资产）分离——本表无 user_id，是公共资产。

结构化字段（company/position/salary/city/job_type 等）供筛选/统计/分页，
content 是全文唯一载体（D2 脏标记模式，同 resumes/knowledge_assets），
向量索引进 Chroma 公共集合 market_public（所有用户共享一份）。
"""

from datetime import datetime, timezone

from sqlalchemy import (
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
    # 数据管道来源（内部幂等键，API 不对外暴露）：campus / upcv / upcv_recruitments / alljobs / referral
    source: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    # 源 JSON 原始 id（幂等 upsert 唯一键）
    external_id: Mapped[str] = mapped_column(String(100), nullable=False)
    # 岗位类型：campus / social / intern
    job_type: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    company: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    position: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    city: Mapped[str | None] = mapped_column(String(255), nullable=True)  # 可逗号/顿号分隔多城市
    industry: Mapped[str | None] = mapped_column(String(255), nullable=True)
    salary: Mapped[str | None] = mapped_column(String(100), nullable=True)
    degree: Mapped[str | None] = mapped_column(String(100), nullable=True)  # 学历要求
    deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_expired: Mapped[bool] = mapped_column(default=False, nullable=False, index=True)
    # 投递链接（公开渠道，源 URL 可能带长查询串）
    apply_url: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    # 真实发布时间（源字段归一化写入，缺失回退 created_at 排序）
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    # 全文（D2 脏标记唯一载体）
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    indexed_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
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
