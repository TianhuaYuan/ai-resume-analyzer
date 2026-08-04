"""resume_modules.source: 模块内容来源标注（G 可信度控制）

Revision ID: 020_resume_module_source
Revises: 019_interview_session
Create Date: 2026-08-04 20:00:00.000000

改写/翻译类 AI 工具在提交模块时标注 source：
- fact：直接来自简历事实
- inferred：AI 推断/补充（需用户核对）
- mixed：混合

前端据此给非 fact 模块加视觉标记与逐条审阅入口。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "020_resume_module_source"
down_revision: Union[str, None] = "019_interview_session"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "resume_modules",
        sa.Column("source", sa.String(20), nullable=False, server_default="fact"),
    )


def downgrade() -> None:
    op.drop_column("resume_modules", "source")
