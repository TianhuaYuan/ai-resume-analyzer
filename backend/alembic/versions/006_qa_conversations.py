"""add qa_conversations table + conversation_id FK to qa_history

Revision ID: 006_qa_conversations
Revises: 005_qa_process_trace
Create Date: 2026-08-01 06:00:00.000000

每份简历支持多个独立对话线程：
- 新建 qa_conversations 表（id/user_id/resume_id/title/created_at/updated_at）
- qa_history 加 nullable conversation_id FK（SET NULL on delete）
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "006_qa_conversations"
down_revision: Union[str, None] = "005_qa_process_trace"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "qa_conversations",
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
        sa.Column(
            "title", sa.String(100), nullable=False, server_default="新对话"
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_qa_conversations_user_id", "qa_conversations", ["user_id"])
    op.create_index("ix_qa_conversations_resume_id", "qa_conversations", ["resume_id"])

    op.add_column(
        "qa_history",
        sa.Column(
            "conversation_id",
            sa.Integer(),
            sa.ForeignKey("qa_conversations.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_qa_history_conversation_id", "qa_history", ["conversation_id"])


def downgrade() -> None:
    op.drop_index("ix_qa_history_conversation_id", table_name="qa_history")
    op.drop_column("qa_history", "conversation_id")
    op.drop_index("ix_qa_conversations_resume_id", table_name="qa_conversations")
    op.drop_index("ix_qa_conversations_user_id", table_name="qa_conversations")
    op.drop_table("qa_conversations")
