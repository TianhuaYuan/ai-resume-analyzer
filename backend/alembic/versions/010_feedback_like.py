"""create feedback_likes table

Revision ID: 010_feedback_like
Revises: 009_campus_track
Create Date: 2026-08-02 16:00:00.000000

用户反馈点赞表：支持对反馈内容点赞。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "010_feedback_like"
down_revision: Union[str, None] = "009_campus_track"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "feedback_likes",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "feedback_id",
            sa.Integer(),
            sa.ForeignKey("user_feedback.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "feedback_id", name="uq_feedback_like_user_feedback"),
    )
    op.create_index("ix_feedback_likes_user_id", "feedback_likes", ["user_id"])
    op.create_index("ix_feedback_likes_feedback_id", "feedback_likes", ["feedback_id"])


def downgrade() -> None:
    op.drop_index("ix_feedback_likes_feedback_id", table_name="feedback_likes")
    op.drop_index("ix_feedback_likes_user_id", table_name="feedback_likes")
    op.drop_table("feedback_likes")
