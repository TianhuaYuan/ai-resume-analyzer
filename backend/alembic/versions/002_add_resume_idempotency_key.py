"""add idempotency_key to resumes

Revision ID: 002_add_resume_idempotency_key
Revises: 001_init_schema
Create Date: 2026-07-17 15:40:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '002_add_resume_idempotency_key'
down_revision: Union[str, Sequence[str], None] = '001_init_schema'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """给 resumes 表新增 idempotency_key 列（可空 + 索引）。"""
    op.add_column(
        'resumes',
        sa.Column('idempotency_key', sa.String(64), nullable=True),
    )
    op.create_index('ix_resumes_idempotency_key', 'resumes', ['idempotency_key'])


def downgrade() -> None:
    """逆操作：删除 idempotency_key 列与索引。"""
    op.drop_index('ix_resumes_idempotency_key', table_name='resumes')
    op.drop_column('resumes', 'idempotency_key')
