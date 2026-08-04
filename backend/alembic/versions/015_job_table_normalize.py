"""normalize market_assets to job-only columns

Revision ID: 015_job_table_normalize
Revises: 014_add_parse_progress
Create Date: 2026-08-03 22:00:00.000000

产品更新：岗位表结构统一。
- 新增 apply_url / published_at（从 payload 提升为正式列，published_at 供排序）
- 删除通用资产遗留列：asset_type / is_published / version / payload
- source 保留仅作内部幂等键（API 不再暴露）
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "015_job_table_normalize"
down_revision: Union[str, None] = "014_add_parse_progress"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. 新增岗位列（apply_url 用 VARCHAR(2000)，源 URL 可能带长查询串）
    op.add_column("market_assets", sa.Column("apply_url", sa.String(2000), nullable=True))
    op.add_column(
        "market_assets",
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_market_assets_published_at", "market_assets", ["published_at"]
    )

    # 2. 从 payload JSON 回填（存量数据，payload 为 NULL 时跳过；超长截断）
    op.execute(
        "UPDATE market_assets "
        "SET apply_url = LEFT(JSON_UNQUOTE(JSON_EXTRACT(payload, '$.apply_url')), 2000) "
        "WHERE payload IS NOT NULL AND JSON_EXTRACT(payload, '$.apply_url') IS NOT NULL"
    )
    # published_at：规范化 ISO 格式（T→空格、去 Z、截 19 位），仅回填 YYYY-MM-DD 开头的合法行
    op.execute(
        "UPDATE market_assets "
        "SET published_at = CAST(LEFT(REPLACE(REPLACE("
        "JSON_UNQUOTE(JSON_EXTRACT(payload, '$.published_at')), 'T', ' '), 'Z', ''), 19) AS DATETIME) "
        "WHERE payload IS NOT NULL "
        "AND JSON_UNQUOTE(JSON_EXTRACT(payload, '$.published_at')) REGEXP '^[0-9]{4}-[0-9]{2}-[0-9]{2}'"
    )

    # 3. 删除通用资产遗留列
    op.drop_column("market_assets", "asset_type")
    op.drop_column("market_assets", "is_published")
    op.drop_column("market_assets", "version")
    op.drop_column("market_assets", "payload")


def downgrade() -> None:
    # 重建通用资产列（payload 原 JSON 无法精确恢复，标注数据不可逆）
    op.add_column(
        "market_assets",
        sa.Column("payload", sa.JSON(), nullable=True),
    )
    op.add_column(
        "market_assets",
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column(
        "market_assets",
        sa.Column("is_published", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column(
        "market_assets",
        sa.Column("asset_type", sa.String(20), nullable=False, server_default="job"),
    )
    op.drop_index("ix_market_assets_published_at", table_name="market_assets")
    op.drop_column("market_assets", "published_at")
    op.drop_column("market_assets", "apply_url")
