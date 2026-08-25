"""resumes 增加模块内容修订号。

Revision ID: 028_resume_module_revision
Revises: 027_add_user_is_admin
Create Date: 2026-08-25
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "028_resume_module_revision"
down_revision: Union[str, None] = "027_add_user_is_admin"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "resumes",
        sa.Column(
            "module_revision",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )


def downgrade() -> None:
    op.drop_column("resumes", "module_revision")
