"""阶段 4: pending_changes + jd_match_reports 两张新表

Revision ID: 024_pending_changes_jd_reports
Revises: 023_drop_market_campus
Create Date: 2026-08-06 16:00:00.000000

E2 改写审阅队列（pending_changes）：改写类工具落库后生成字段级 diff 记录，
前端逐条接受/丢弃，user_id 隔离。
I1 JD 6-block 报告落库（jd_match_reports）：JDMatchTool 分块报告持久化，
同 (user, resume, jd_hash) 幂等覆盖。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "024_pending_changes_jd_reports"
down_revision: Union[str, None] = "023_drop_market_campus"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "pending_changes",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "resume_id",
            sa.Integer(),
            sa.ForeignKey("resumes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("tool_name", sa.String(50), nullable=False),
        sa.Column("module_type", sa.String(50), nullable=False),
        sa.Column("field_path", sa.String(255), nullable=False),
        sa.Column("before", sa.JSON(), nullable=True),
        sa.Column("after", sa.JSON(), nullable=True),
        sa.Column("rationale", sa.String(500), nullable=False, server_default=""),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default="pending",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_pending_changes_resume_id", "pending_changes", ["resume_id"])
    op.create_index("ix_pending_changes_user_id", "pending_changes", ["user_id"])

    op.create_table(
        "jd_match_reports",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "resume_id",
            sa.Integer(),
            sa.ForeignKey("resumes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("jd_text_hash", sa.String(64), nullable=False),
        sa.Column("jd_text", sa.Text(), nullable=False),
        sa.Column("report", sa.JSON(), nullable=False),
        sa.Column("overall", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("band", sa.String(20), nullable=False, server_default="needsWork"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "resume_id",
            "jd_text_hash",
            name="uq_jd_report_user_resume_hash",
        ),
    )
    op.create_index("ix_jd_match_reports_user_id", "jd_match_reports", ["user_id"])
    op.create_index("ix_jd_match_reports_resume_id", "jd_match_reports", ["resume_id"])


def downgrade() -> None:
    op.drop_table("jd_match_reports")
    op.drop_table("pending_changes")
