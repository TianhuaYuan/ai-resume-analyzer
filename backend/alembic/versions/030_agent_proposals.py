"""Add reviewable Agent proposals."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "030_agent_proposals"
down_revision: Union[str, None] = "029_agent_runs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "agent_proposals",
        sa.Column("proposal_id", sa.String(length=64), nullable=False),
        sa.Column("run_id", sa.String(length=64), nullable=True),
        sa.Column("call_id", sa.String(length=128), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("resume_id", sa.Integer(), nullable=False),
        sa.Column("base_revision", sa.Integer(), nullable=False),
        sa.Column("operations", sa.JSON(), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        # MySQL does not allow a server default on TEXT. The ORM supplies the
        # application-level default (""), so keeping this column non-null is
        # sufficient and preserves cross-database migration compatibility.
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="draft"),
        sa.Column("applied_revision", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["agent_runs.run_id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["resume_id"], ["resumes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("proposal_id"),
        sa.UniqueConstraint("idempotency_key"),
    )
    op.create_index("ix_agent_proposals_run_id", "agent_proposals", ["run_id"])
    op.create_index("ix_agent_proposals_user_id", "agent_proposals", ["user_id"])
    op.create_index("ix_agent_proposals_resume_id", "agent_proposals", ["resume_id"])
    op.create_index("ix_agent_proposals_content_hash", "agent_proposals", ["content_hash"])
    op.create_index("ix_agent_proposals_status", "agent_proposals", ["status"])


def downgrade() -> None:
    op.drop_index("ix_agent_proposals_status", table_name="agent_proposals")
    op.drop_index("ix_agent_proposals_content_hash", table_name="agent_proposals")
    op.drop_index("ix_agent_proposals_resume_id", table_name="agent_proposals")
    op.drop_index("ix_agent_proposals_user_id", table_name="agent_proposals")
    op.drop_index("ix_agent_proposals_run_id", table_name="agent_proposals")
    op.drop_table("agent_proposals")
