"""add parse_progress to resumes

Revision ID: 014_add_parse_progress
Revises: 013_drop_sample_guide_assets
Create Date: 2026-08-03 21:30:00.000000

上传简历后台处理流水线新增进度字段 parse_progress，
前端在 processing 期间展示解析进度条（parsing → materializing → done）。
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "014_add_parse_progress"
down_revision: Union[str, None] = "013_drop_sample_guide_assets"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("resumes", sa.Column("parse_progress", mysql.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("resumes", "parse_progress")
