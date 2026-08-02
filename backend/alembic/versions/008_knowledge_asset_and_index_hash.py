"""add knowledge_assets table + resume index hash columns

Revision ID: 008_knowledge_asset_idx
Revises: 007_analytics_events
Create Date: 2026-08-02

T3 (D2 版本化快照 + 资产模型)：
- resumes 增加 content_hash / indexed_hash（脏标记：content_hash != indexed_hash → 索引过期）
- 新增 knowledge_assets 通用表承载 jd/interview/note 资产

注意：revision ID 必须 <= 32 字符（alembic_version.version_num 为 VARCHAR(32)），
早期误用长 ID 导致 "Data too long"，已改为 008_knowledge_asset_idx。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "008_knowledge_asset_idx"
down_revision: Union[str, None] = "007_analytics_events"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. resumes 增加索引状态哈希 + 索引版本号
    op.add_column(
        "resumes",
        sa.Column("content_hash", sa.String(64), nullable=True),
    )
    op.add_column(
        "resumes",
        sa.Column("indexed_hash", sa.String(64), nullable=True),
    )
    op.add_column(
        "resumes",
        sa.Column("index_version", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )

    # 2. knowledge_assets 通用表
    op.create_table(
        "knowledge_assets",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("asset_type", sa.String(20), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=True),
        sa.Column("indexed_hash", sa.String(64), nullable=True),
        sa.Column("is_draft", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("index_version", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("(UTC_TIMESTAMP)"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("(UTC_TIMESTAMP)"),
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_knowledge_assets_user_id", "knowledge_assets", ["user_id"])
    op.create_index(
        "ix_knowledge_assets_user_type",
        "knowledge_assets",
        ["user_id", "asset_type"],
    )


def downgrade() -> None:
    op.drop_index("ix_knowledge_assets_user_type", table_name="knowledge_assets")
    op.drop_index("ix_knowledge_assets_user_id", table_name="knowledge_assets")
    op.drop_table("knowledge_assets")
    op.drop_column("resumes", "index_version")
    op.drop_column("resumes", "indexed_hash")
    op.drop_column("resumes", "content_hash")
