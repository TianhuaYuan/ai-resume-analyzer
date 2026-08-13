"""create analytics_events table

Revision ID: 007_analytics_events
Revises: 006_qa_conversations
Create Date: 2026-08-01 07:00:00.000000

产品分析事件表（models/analytics_event.py 一直无对应 migration，
导致 /api/v1/track/events 写入报 500「事件写入失败」）。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "007_analytics_events"
down_revision: Union[str, None] = "006_qa_conversations"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "analytics_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("event_name", sa.String(50), nullable=False),
        sa.Column("source", sa.String(50), nullable=True),
        # 注意：模型类属性名是 event_metadata，但显式列名 "metadata"
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("(UTC_TIMESTAMP)"),
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_analytics_events_user_id", "analytics_events", ["user_id"])
    op.create_index("ix_analytics_events_event_name", "analytics_events", ["event_name"])
    op.create_index(
        "ix_analytics_events_name_time",
        "analytics_events",
        ["event_name", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_analytics_events_name_time", table_name="analytics_events")
    op.drop_index("ix_analytics_events_event_name", table_name="analytics_events")
    op.drop_index("ix_analytics_events_user_id", table_name="analytics_events")
    op.drop_table("analytics_events")
