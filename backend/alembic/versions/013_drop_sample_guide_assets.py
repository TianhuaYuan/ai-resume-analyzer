"""drop sample/guide market assets

Revision ID: 013_drop_sample_guide_assets
Revises: 012_resume_updated_at
Create Date: 2026-08-03 21:00:00.000000

产品更新：移除 简历范文(sample) / 求职攻略(guide) 模块。
market_assets 表同时承载 岗位(job)/范文(sample)/攻略(guide) 三类，
本迁移仅删除 sample/guide 数据行，保留表结构与岗位数据（校招/社招不受影响）。
"""
from typing import Sequence, Union

from alembic import op


revision: str = "013_drop_sample_guide_assets"
down_revision: Union[str, None] = "012_resume_updated_at"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("DELETE FROM market_assets WHERE asset_type IN ('sample', 'guide')")


def downgrade() -> None:
    # 数据已删除且无备份，无法恢复（no-op 保证迁移链可回退）。
    pass
