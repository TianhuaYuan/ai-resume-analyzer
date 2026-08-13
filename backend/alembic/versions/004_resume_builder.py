"""resume builder & react agent migration

Revision ID: 004_resume_builder
Revises: 003_uq_resume_user_idempotency
Create Date: 2026-07-31 06:00:00.000000

S1 T1: alembic 004 全量迁移
- resumes 加 source/style/version/expires_at；status 兼容 draft
- 新表 resume_modules / job_applications / audit_logs / qa_feedback / user_feedback
- qa_history 加 status；users 加 password_changed_at
- 已有行回填 source='upload'/version=1/status='complete'
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "004_resume_builder"
down_revision: Union[str, Sequence[str], None] = "003_uq_resume_user_idempotency"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """执行升级：加列 + 建新表 + 回填。"""
    # ── 1. resumes 加列 ──
    op.add_column("resumes", sa.Column("source", sa.String(20), server_default="upload", nullable=False))
    op.add_column("resumes", sa.Column("style", sa.JSON(), nullable=True))
    op.add_column("resumes", sa.Column("version", sa.Integer(), server_default="1", nullable=False))
    op.add_column("resumes", sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True))

    # ── 2. users 加列 ──
    op.add_column("users", sa.Column("password_changed_at", sa.DateTime(timezone=True), nullable=True))

    # ── 3. qa_history 加列 ──
    op.add_column("qa_history", sa.Column("status", sa.String(20), server_default="complete", nullable=False))

    # ── 4. 回填已有数据 ──
    op.execute("UPDATE resumes SET source = 'upload' WHERE source IS NULL")
    op.execute("UPDATE resumes SET version = 1 WHERE version IS NULL")
    op.execute("UPDATE qa_history SET status = 'complete' WHERE status IS NULL")

    # ── 5. 新建 resume_modules 表 ──
    op.create_table(
        "resume_modules",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("resume_id", sa.Integer(), nullable=False),
        sa.Column("module_type", sa.String(50), nullable=False),
        sa.Column("content", sa.JSON(), nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["resume_id"], ["resumes.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("resume_id", "module_type", name="uq_resume_module"),
    )
    op.create_index("ix_resume_modules_resume_id", "resume_modules", ["resume_id"])

    # ── 6. 新建 job_applications 表 ──
    op.create_table(
        "job_applications",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("resume_id", sa.Integer(), nullable=True),
        sa.Column("company", sa.String(100), nullable=False),
        sa.Column("position", sa.String(100), nullable=False),
        sa.Column("city", sa.String(50), nullable=True),
        sa.Column("salary_range", sa.String(50), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["resume_id"], ["resumes.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_job_applications_user_id", "job_applications", ["user_id"])
    op.create_index("ix_job_applications_resume_id", "job_applications", ["resume_id"])

    # ── 7. 新建 audit_logs 表 ──
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("action", sa.String(50), nullable=False),
        sa.Column("target_type", sa.String(50), nullable=True),
        sa.Column("target_id", sa.String(50), nullable=True),
        sa.Column("detail", sa.JSON(), nullable=True),
        sa.Column("ip", sa.String(45), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_audit_logs_user_id", "audit_logs", ["user_id"])

    # ── 8. 新建 qa_feedback 表 ──
    op.create_table(
        "qa_feedback",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("qa_id", sa.Integer(), nullable=False),
        sa.Column("rating", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["qa_id"], ["qa_history.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_qa_feedback_qa_id", "qa_feedback", ["qa_id"])

    # ── 9. 新建 user_feedback 表 ──
    op.create_table(
        "user_feedback",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("type", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), server_default="open", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_user_feedback_user_id", "user_feedback", ["user_id"])


def downgrade() -> None:
    """执行降级：按依赖逆序删除。"""
    # 先删子表，再删父表的新列
    op.drop_table("user_feedback")
    op.drop_table("qa_feedback")
    op.drop_table("audit_logs")
    op.drop_table("job_applications")
    op.drop_table("resume_modules")

    op.drop_column("qa_history", "status")
    op.drop_column("users", "password_changed_at")
    op.drop_column("resumes", "expires_at")
    op.drop_column("resumes", "version")
    op.drop_column("resumes", "style")
    op.drop_column("resumes", "source")
