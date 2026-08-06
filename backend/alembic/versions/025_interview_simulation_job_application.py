"""阶段 5: interview_simulations + job_applications 两张新表

Revision ID: 025_interview_simulation_job_application
Revises: 024_pending_changes_jd_reports
Create Date: 2026-08-06 18:00:00.000000

H1-H3 多轮模拟面试实时状态（interview_simulations）：QuestionPlan + cursor +
followup_index + answers，面试完成时评分卡写入 interview_sessions（复用复盘闭环）。
J 投递状态机（job_applications）：投递追踪 + timeline 时间线 + match_keys 去重 +
jd_scorecard 评分卡 + 软删除垃圾箱（deleted_at）。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "025_interview_simulation_job_application"
down_revision: Union[str, None] = "024_pending_changes_jd_reports"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "interview_simulations",
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
            sa.ForeignKey("resumes.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("target_position", sa.String(100), nullable=False),
        sa.Column("plan", sa.JSON(), nullable=True),
        sa.Column("cursor", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("followup_index", sa.Integer(), nullable=False, server_default="-1"),
        sa.Column("answers", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
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
    )
    op.create_index(
        "ix_interview_simulations_user_id", "interview_simulations", ["user_id"]
    )
    op.create_index(
        "ix_interview_simulations_resume_id", "interview_simulations", ["resume_id"]
    )

    op.create_table(
        "job_applications",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("company", sa.String(120), nullable=False),
        sa.Column("position", sa.String(120), nullable=False),
        sa.Column("url", sa.String(500), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="待投递"),
        sa.Column("priority", sa.String(10), nullable=False, server_default="中"),
        sa.Column("deadline", sa.Date(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("jd_text", sa.Text(), nullable=True),
        sa.Column("jd_scorecard", sa.JSON(), nullable=True),
        sa.Column("match_keys", sa.JSON(), nullable=True),
        sa.Column("normalized_url", sa.String(500), nullable=True),
        sa.Column("timeline", sa.JSON(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
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
    )
    op.create_index("ix_job_applications_user_id", "job_applications", ["user_id"])
    op.create_index("ix_job_applications_status", "job_applications", ["status"])
    op.create_index("ix_job_applications_deleted_at", "job_applications", ["deleted_at"])


def downgrade() -> None:
    op.drop_table("job_applications")
    op.drop_table("interview_simulations")
