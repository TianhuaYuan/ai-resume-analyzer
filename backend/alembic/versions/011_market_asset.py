"""create market_assets table

Revision ID: 011_market_asset
Revises: 010_feedback_like
Create Date: 2026-08-02 18:00:00.000000

市场资产表：公共求职数据（岗位 JD/范文/攻略），所有用户共享。
唯一键 (source, external_id) 支撑幂等同步；content 支持 MySQL FULLTEXT。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "011_market_asset"
down_revision: Union[str, None] = "010_feedback_like"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "market_assets",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column("external_id", sa.String(100), nullable=False),
        sa.Column("asset_type", sa.String(20), nullable=False),
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
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=True),
        sa.Column("indexed_hash", sa.String(64), nullable=True),
        sa.Column("is_published", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("index_version", sa.Integer(), nullable=False, server_default="0"),
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
    # MySQL FULLTEXT（SQLite 测试环境经 Base.metadata.create_all 建表，不受此 DDL 影响）
    op.create_index(
        "ftix_market_assets_content",
        "market_assets",
        ["content"],
        mysql_prefix="FULLTEXT",
    )


def downgrade() -> None:
    op.drop_index("ftix_market_assets_content", table_name="market_assets")
    op.drop_index("ix_market_assets_position", table_name="market_assets")
    op.drop_index("ix_market_assets_company", table_name="market_assets")
    op.drop_index("ix_market_assets_is_expired", table_name="market_assets")
    op.drop_index("ix_market_assets_job_type", table_name="market_assets")
    op.drop_index("ix_market_assets_source", table_name="market_assets")
    op.drop_table("market_assets")
