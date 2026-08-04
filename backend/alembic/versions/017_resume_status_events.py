"""resume status transition events (fieldwork fw_events 对照)

Revision ID: 017_resume_status_events
Revises: 016_entity_link
Create Date: 2026-08-04 14:00:00.000000

简历状态流转事件表（ADD-only）：
- 每次状态迁移（processing/ready/failed/draft）记录 from → to + reason
- 供失败复盘、卡死诊断、前端时间线
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "017_resume_status_events"
down_revision: Union[str, None] = "016_entity_link"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "resume_status_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("resume_id", sa.Integer(), nullable=False),
        sa.Column("from_status", sa.String(20), nullable=True),
        sa.Column("to_status", sa.String(20), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["resume_id"], ["resumes.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_resume_status_events_resume_id", "resume_status_events", ["resume_id"])


def downgrade() -> None:
    op.drop_index("ix_resume_status_events_resume_id", table_name="resume_status_events")
    op.drop_table("resume_status_events")
