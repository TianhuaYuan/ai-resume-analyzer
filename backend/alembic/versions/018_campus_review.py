"""campus review: add campus_tracks review columns + campus_track_events table

Revision ID: 018_campus_review
Revises: 017_resume_status_events
Create Date: 2026-08-04 15:00:00.000000

求职复盘（B/E3）：
- campus_tracks 加 4 个可空复盘列：date_applied / source / rejection_reason / stage_reached
- 新建 campus_track_events（ADD-only 状态变更事件历史，复刻 resume_status_events 风格）
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "018_campus_review"
down_revision: Union[str, None] = "017_resume_status_events"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. campus_tracks 加复盘列（全部可空，向后兼容既有行）
    op.add_column("campus_tracks", sa.Column("date_applied", sa.Date(), nullable=True))
    op.add_column("campus_tracks", sa.Column("source", sa.String(50), nullable=True))
    op.add_column("campus_tracks", sa.Column("rejection_reason", sa.Text(), nullable=True))
    op.add_column("campus_tracks", sa.Column("stage_reached", sa.String(50), nullable=True))

    # 2. campus_track_events：ADD-only 事件历史
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


def downgrade() -> None:
    op.drop_index("ix_campus_track_events_user_record", table_name="campus_track_events")
    op.drop_table("campus_track_events")
    op.drop_column("campus_tracks", "stage_reached")
    op.drop_column("campus_tracks", "rejection_reason")
    op.drop_column("campus_tracks", "source")
    op.drop_column("campus_tracks", "date_applied")
