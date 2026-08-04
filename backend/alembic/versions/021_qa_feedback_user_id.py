"""qa_feedback 增加 user_id / updated_at 与 (user_id, qa_id) 唯一约束

Revision ID: 021_qa_feedback_user_id
Revises: 020_resume_module_source
Create Date: 2026-08-04 22:00:00.000000

背景：qa_feedback 原表无 user_id，靠"先删后插"硬保证一人一条，不可审计。
本次升级：
- 新增 user_id 列，从 qa_history 反查回填既有数据（子查询写法 MySQL/SQLite 兼容）
- 新增 updated_at 列，支持记录"用户改主意"的更新时间
- 新增唯一约束 uq_qa_feedback_user_qa(user_id, qa_id)，从结构上保证一人一条
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "021_qa_feedback_user_id"
down_revision: Union[str, None] = "020_resume_module_source"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. 先加可空列，避免加列即 NOT NULL 失败
    op.add_column("qa_feedback", sa.Column("user_id", sa.Integer(), nullable=True))
    op.add_column(
        "qa_feedback",
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )

    # 2. 回填归属：从 qa_history 反查 user_id（子查询写法 MySQL/SQLite 双兼容）
    op.execute(
        "UPDATE qa_feedback SET user_id = "
        "(SELECT qa_history.user_id FROM qa_history "
        " WHERE qa_history.id = qa_feedback.qa_id)"
    )

    # 3. 收紧为 NOT NULL + 唯一约束 + 索引 + 默认值
    with op.batch_alter_table("qa_feedback") as batch_op:
        batch_op.alter_column(
            "user_id", existing_type=sa.Integer(), nullable=False
        )
        batch_op.alter_column(
            "updated_at",
            existing_type=sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        )
        batch_op.create_unique_constraint(
            "uq_qa_feedback_user_qa", ["user_id", "qa_id"]
        )
        batch_op.create_index("ix_qa_feedback_user_id", ["user_id"])


def downgrade() -> None:
    with op.batch_alter_table("qa_feedback") as batch_op:
        batch_op.drop_index("ix_qa_feedback_user_id")
        batch_op.drop_constraint("uq_qa_feedback_user_qa", type_="unique")
        batch_op.alter_column(
            "updated_at",
            existing_type=sa.DateTime(timezone=True),
            nullable=True,
            server_default=None,
        )
    op.drop_column("qa_feedback", "updated_at")
    op.drop_column("qa_feedback", "user_id")
