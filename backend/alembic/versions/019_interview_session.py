"""interview sessions (面试复盘闭环 G：面后记录 → 薄弱点 → 训练推荐)

Revision ID: 019_interview_session
Revises: 018_campus_review
Create Date: 2026-08-04 18:00:00.000000

面试复盘记录表（DeepInterview supabase sessions 对照）：
- company/position/resume_id/jd_text/questions/answers 一次写入（面后记录）
- scorecard 评分卡整块 JSON 事后录入（recorded → reviewed），可重复评分
- scorecard.weak_competencies 作为学习闭环消费契约（→ 训练推荐）
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "019_interview_session"
down_revision: Union[str, None] = "018_campus_review"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "interview_sessions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("company", sa.String(100), nullable=False),
        sa.Column("position", sa.String(100), nullable=False),
        sa.Column("resume_id", sa.Integer(), nullable=True),
        sa.Column("jd_text", sa.Text(), nullable=True),
        sa.Column("questions", sa.JSON(), nullable=True),
        sa.Column("answers", sa.JSON(), nullable=True),
        sa.Column("scorecard", sa.JSON(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="recorded"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["resume_id"], ["resumes.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_interview_sessions_user_id", "interview_sessions", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_interview_sessions_user_id", table_name="interview_sessions")
    op.drop_table("interview_sessions")
