"""知识资产归档来源 + 面试复盘关联投递

Revision ID: 026_archive_source_link
Revises: 025_interview_simulation_job_application
Create Date: 2026-08-06

职责重定位（知识资产收敛为聚合检索视图，JD/面试录入收口到业务模块）：
- interview_sessions 增加 job_application_id：面试复盘挂到投递看板的对应面次，
  关联投递且未填 JD 时自动取投递 jd_text（均含归属校验）；
- knowledge_assets 增加 source_type/source_id + 唯一约束 (user_id, source_type, source_id)：
  归档幂等（同来源 re-archive 覆盖更新，见 services/asset_service.upsert_asset_by_source）；
  手动新建的 note 资产 source 为 NULL（多行 NULL 不参与唯一约束）。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "026_archive_source_link"
down_revision: Union[str, None] = "025_interview_simulation_job_application"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. 面试复盘关联投递（可空 FK，存量数据不受影响）
    op.add_column(
        "interview_sessions",
        sa.Column("job_application_id", sa.Integer(), nullable=True),
    )
    op.create_index(
        "ix_interview_sessions_job_application_id",
        "interview_sessions",
        ["job_application_id"],
    )
    op.create_foreign_key(
        "fk_interview_sessions_job_application",
        "interview_sessions",
        "job_applications",
        ["job_application_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # 2. 知识资产归档来源标记 + 唯一约束（幂等 upsert）
    op.add_column(
        "knowledge_assets",
        sa.Column("source_type", sa.String(40), nullable=True),
    )
    op.add_column(
        "knowledge_assets",
        sa.Column("source_id", sa.Integer(), nullable=True),
    )
    op.create_unique_constraint(
        "uq_knowledge_assets_source",
        "knowledge_assets",
        ["user_id", "source_type", "source_id"],
    )


def downgrade() -> None:
    with op.batch_alter_table("knowledge_assets") as batch_op:
        batch_op.drop_constraint("uq_knowledge_assets_source", type_="unique")
    op.drop_column("knowledge_assets", "source_id")
    op.drop_column("knowledge_assets", "source_type")

    with op.batch_alter_table("interview_sessions") as batch_op:
        batch_op.drop_constraint(
            "fk_interview_sessions_job_application", type_="foreignkey"
        )
        batch_op.drop_index("ix_interview_sessions_job_application_id")
    op.drop_column("interview_sessions", "job_application_id")
