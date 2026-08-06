"""drop market/campus tables: 静态爬虫数据管线移除（M1）

Revision ID: 023_drop_market_campus
Revises: 022_resume_language_family
Create Date: 2026-08-06 12:00:00.000000

静态爬虫数据管线彻底移除（岗位能力由 search_jobs_live 实时搜索承接）后，
drop 三张市场/校招表：
- market_assets（岗位/范文/攻略，公共数据，011 创建 / 015 规范化）
- campus_tracks（校招求职跟踪，009 创建 / 018 加复盘列）
- campus_track_events（复盘状态事件历史，018 创建）

迁移链保留：013 曾 DELETE FROM market_assets，本迁移只 drop 表，不改写历史迁移。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "023_drop_market_campus"
down_revision: Union[str, None] = "022_resume_language_family"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_table("campus_track_events")
    op.drop_table("campus_tracks")
    op.drop_table("market_assets")


def downgrade() -> None:
    # 重建表结构（对齐 009/011/015/018 的最终形态；存量数据不可恢复）
    op.create_table(
        "campus_tracks",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("campus_record_id", sa.String(100), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("date_applied", sa.Date(), nullable=True),
        sa.Column("source", sa.String(50), nullable=True),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column("stage_reached", sa.String(50), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "campus_record_id", name="uq_campus_track_user_record"),
    )
    op.create_index("ix_campus_tracks_user_id", "campus_tracks", ["user_id"])

    op.create_table(
        "campus_track_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("campus_record_id", sa.String(100), nullable=False),
        sa.Column("event_type", sa.String(30), nullable=False),
        sa.Column("from_status", sa.String(20), nullable=True),
        sa.Column("to_status", sa.String(20), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("occurred_at", sa.Date(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index(
        "ix_campus_track_events_user_record",
        "campus_track_events",
        ["user_id", "campus_record_id"],
    )

    op.create_table(
        "market_assets",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column("external_id", sa.String(100), nullable=False),
        sa.Column("job_type", sa.String(20), nullable=True),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("company", sa.String(255), nullable=True),
        sa.Column("position", sa.String(255), nullable=True),
        sa.Column("city", sa.String(255), nullable=True),
        sa.Column("industry", sa.String(255), nullable=True),
        sa.Column("salary", sa.String(100), nullable=True),
        sa.Column("degree", sa.String(100), nullable=True),
        sa.Column("deadline", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_expired", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=True),
        sa.Column("indexed_hash", sa.String(64), nullable=True),
        sa.Column("index_version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("apply_url", sa.String(2000), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source", "external_id", name="uq_market_source_external"),
    )
    op.create_index("ix_market_assets_source", "market_assets", ["source"])
    op.create_index("ix_market_assets_job_type", "market_assets", ["job_type"])
    op.create_index("ix_market_assets_is_expired", "market_assets", ["is_expired"])
    op.create_index("ix_market_assets_company", "market_assets", ["company"])
    op.create_index("ix_market_assets_position", "market_assets", ["position"])
    op.create_index("ix_market_assets_published_at", "market_assets", ["published_at"])
