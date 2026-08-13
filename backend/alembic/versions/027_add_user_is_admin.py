"""users 增加 is_admin 列（本地个人工具：首注册用户即管理员）

Revision ID: 027_add_user_is_admin
Revises: 026_archive_source_link
Create Date: 2026-08-13

- users.is_admin：由 BOOTSTRAP_FIRST_USER_ADMIN 开关在注册时置位
  （services/auth_service.register_user），配合 ADMIN_EMAILS 白名单双轨判定。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "027_add_user_is_admin"
down_revision: Union[str, None] = "026_archive_source_link"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("is_admin", sa.Boolean(), nullable=False, server_default=sa.text("0")),
    )


def downgrade() -> None:
    op.drop_column("users", "is_admin")
