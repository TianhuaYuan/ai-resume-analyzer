"""resumes.language + resumes.family_id：多语言版本管理（G）

Revision ID: 022_resume_language_family
Revises: 021_qa_feedback_user_id
Create Date: 2026-08-04 22:00:00.000000

「一份简历 N 语言版本」：copy_resume_as_new 复制出的语言副本与源简历
归属同一 family（family_id 指向族根），language 标注副本语言（如 zh/en）。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "022_resume_language_family"
down_revision: Union[str, None] = "021_qa_feedback_user_id"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("resumes", sa.Column("language", sa.String(20), nullable=True))
    op.add_column(
        "resumes",
        sa.Column("family_id", sa.Integer(), nullable=True),
    )
    op.create_index("ix_resumes_family_id", "resumes", ["family_id"])


def downgrade() -> None:
    op.drop_index("ix_resumes_family_id", table_name="resumes")
    op.drop_column("resumes", "family_id")
    op.drop_column("resumes", "language")
