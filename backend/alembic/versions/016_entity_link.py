"""A3 entity linking: resume_entities / resume_entity_facts / resume_episodes

Revision ID: 016_entity_link
Revises: 015_job_table_normalize
Create Date: 2026-08-04 12:00:00.000000

实体链接（借鉴 graphiti 双时态 + mem0 双向索引）：
- resume_entities：简历命名实体（name_normalized 消解快路径索引列，linked_memory_ids JSON）
- resume_entity_facts：实体的原子事实，ADD-only（(entity_id, fact_text_norm) 唯一约束天然去重），
  invalid_at/expired_at 双时态失效标记（不物理删除）
- resume_episodes：实体/事实的来源情节锚点（fact.episode_id 溯源）
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "016_entity_link"
down_revision: Union[str, None] = "015_job_table_normalize"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "resume_entities",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("resume_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("name_normalized", sa.String(128), nullable=False),
        sa.Column("entity_type", sa.String(32), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("linked_memory_ids", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["resume_id"], ["resumes.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_resume_entities_user_id", "resume_entities", ["user_id"])
    op.create_index("ix_resume_entities_resume_id", "resume_entities", ["resume_id"])
    op.create_index("ix_resume_entities_name_normalized", "resume_entities", ["name_normalized"])

    op.create_table(
        "resume_entity_facts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("resume_id", sa.Integer(), nullable=False),
        sa.Column("entity_id", sa.Integer(), nullable=False),
        sa.Column("episode_id", sa.Integer(), nullable=False),
        sa.Column("fact_text", sa.Text(), nullable=False),
        sa.Column("fact_text_norm", sa.String(500), nullable=False),
        sa.Column("importance", sa.Float(), nullable=False),
        sa.Column("valid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("invalid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("linked_memory_id", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["resume_id"], ["resumes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["entity_id"], ["resume_entities.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["episode_id"], ["resume_episodes.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("entity_id", "fact_text_norm", name="uq_entity_fact_norm"),
    )
    op.create_index("ix_resume_entity_facts_user_id", "resume_entity_facts", ["user_id"])
    op.create_index("ix_resume_entity_facts_resume_id", "resume_entity_facts", ["resume_id"])
    op.create_index("ix_resume_entity_facts_entity_id", "resume_entity_facts", ["entity_id"])
    op.create_index("ix_resume_entity_facts_episode_id", "resume_entity_facts", ["episode_id"])

    op.create_table(
        "resume_episodes",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("resume_id", sa.Integer(), nullable=False),
        sa.Column("source_type", sa.String(32), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("valid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["resume_id"], ["resumes.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_resume_episodes_user_id", "resume_episodes", ["user_id"])
    op.create_index("ix_resume_episodes_resume_id", "resume_episodes", ["resume_id"])


def downgrade() -> None:
    op.drop_index("ix_resume_episodes_resume_id", table_name="resume_episodes")
    op.drop_index("ix_resume_episodes_user_id", table_name="resume_episodes")
    op.drop_table("resume_episodes")

    op.drop_index("ix_resume_entity_facts_episode_id", table_name="resume_entity_facts")
    op.drop_index("ix_resume_entity_facts_entity_id", table_name="resume_entity_facts")
    op.drop_index("ix_resume_entity_facts_resume_id", table_name="resume_entity_facts")
    op.drop_index("ix_resume_entity_facts_user_id", table_name="resume_entity_facts")
    op.drop_table("resume_entity_facts")

    op.drop_index("ix_resume_entities_name_normalized", table_name="resume_entities")
    op.drop_index("ix_resume_entities_resume_id", table_name="resume_entities")
    op.drop_index("ix_resume_entities_user_id", table_name="resume_entities")
    op.drop_table("resume_entities")
