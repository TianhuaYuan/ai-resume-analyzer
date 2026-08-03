"""add updated_at to resumes

Revision ID: 012_resume_updated_at
Revises: 011_market_asset
Create Date: 2026-08-03 20:00:00.000000

简历表增加 updated_at 字段，用于前端展示最新修改时间。
已有数据用 created_at 填充。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "012_resume_updated_at"
down_revision: Union[str, None] = "011_market_asset"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "resumes",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    # 已有数据用 created_at 填充
    op.execute("UPDATE resumes SET updated_at = created_at")


def downgrade() -> None:
    op.drop_column("resumes", "updated_at")
