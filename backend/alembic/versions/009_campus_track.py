"""create campus_tracks table

Revision ID: 009_campus_track
Revises: 008_knowledge_asset_and_index_hash
Create Date: 2026-08-02 15:00:00.000000

校招求职跟踪表：用户对每条校招记录设置求职进度和备注。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "009_campus_track"
down_revision: Union[str, None] = "008_knowledge_asset_idx"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
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
    op.create_index(
        "ix_campus_tracks_user_id",
        "campus_tracks",
        ["user_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_campus_tracks_user_id", table_name="campus_tracks")
    op.drop_table("campus_tracks")
