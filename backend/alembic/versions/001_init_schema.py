"""init schema

Revision ID: 001_init_schema
Revises:
Create Date: 2026-07-03 20:02:50.735174

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "001_init_schema"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """创建 users / resumes / qa_history 三张表。"""
    # 创建 users 表
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("username", sa.String(50), nullable=False),
        sa.Column("email", sa.String(100), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_users_username", "users", ["username"], unique=True)
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    # 创建 resumes 表
    op.create_table(
        "resumes",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("file_path", sa.String(512), nullable=False),
        sa.Column("parsed_text", sa.Text(), nullable=False),
        sa.Column("chunk_count", sa.Integer(), server_default="0"),
        sa.Column("status", sa.String(20), nullable=False, server_default="processing"),
        sa.Column("status_message", sa.String(255), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_resumes_user_id", "resumes", ["user_id"])

    # 创建 qa_history 表
    op.create_table(
        "qa_history",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("resume_id", sa.Integer(), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("sources", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["resume_id"], ["resumes.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_qa_history_user_id", "qa_history", ["user_id"])
    op.create_index("ix_qa_history_resume_id", "qa_history", ["resume_id"])


def downgrade() -> None:
    """按依赖顺序逆序删除三张表。"""
    op.drop_table("qa_history")
    op.drop_table("resumes")
    op.drop_table("users")
