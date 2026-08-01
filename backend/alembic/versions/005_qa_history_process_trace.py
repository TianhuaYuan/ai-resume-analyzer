"""qa_history add process_trace column

Revision ID: 005_qa_process_trace
Revises: 004_resume_builder
Create Date: 2026-08-01 05:00:00.000000

Spec 行 459: DB 存完整 prompt（system + 记忆注入 + 工具序列 + 模型），
供 A12#71 few-shot 导出使用。SSE done 事件同名 field 只发紧凑摘要。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "005_qa_process_trace"
down_revision: Union[str, None] = "004_resume_builder"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("qa_history", sa.Column("process_trace", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("qa_history", "process_trace")
