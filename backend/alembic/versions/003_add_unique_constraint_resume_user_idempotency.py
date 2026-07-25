"""add unique constraint on resumes(user_id, idempotency_key)

Revision ID: 003_uq_resume_user_idempotency
Revises: 002_add_resume_idempotency_key
Create Date: 2026-07-24 22:00:00.000000

P1-9: 给 resumes 表 (user_id, idempotency_key) 加 UNIQUE 约束，
让并发同 key 上传在 DB 层兜底（应用层短路检查 + DB 唯一约束双重防御）。

注意：
- idempotency_key 允许 NULL，标准 SQL 下多个 NULL 不冲突（MySQL/PostgreSQL/SQLite 均遵守）。
- 约束名 uq_resume_user_idempotency 与代码层 IntegrityError 处理保持一致。
"""

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "003_uq_resume_user_idempotency"
down_revision: Union[str, Sequence[str], None] = "002_add_resume_idempotency_key"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """给 resumes 表新增 (user_id, idempotency_key) 复合唯一约束。"""
    op.create_unique_constraint(
        "uq_resume_user_idempotency",
        "resumes",
        ["user_id", "idempotency_key"],
    )


def downgrade() -> None:
    """逆操作：删除 (user_id, idempotency_key) 复合唯一约束。"""
    op.drop_constraint("uq_resume_user_idempotency", "resumes", type_="unique")
