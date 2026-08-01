"""T34: 管理员后台服务层。

提供审计日志查询、用户列表（脱敏）、系统级统计、模板列表等能力。
所有函数均为 async，接收 AsyncSession（统计/列表/审计日志），模板列表为静态数据无需 DB。
"""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.audit_log import AuditLog
from models.job_application import JobApplication
from models.qa_history import QAHistory
from models.resume import Resume
from models.user import User
from models.user_feedback import UserFeedback

# 3 套内置模板（与 backend/templates/*.html 对齐）
# id = 文件名（template_id），name/description 为管理员后台展示用
_TEMPLATES: list[dict[str, str]] = [
    {"id": "default", "name": "经典", "description": "经典模板"},
    {"id": "minimal", "name": "极简", "description": "极简模板"},
    {"id": "business", "name": "商务", "description": "商务模板"},
]


async def list_audit_logs(
    db: AsyncSession,
    action: str | None = None,
    user_id: int | None = None,
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[AuditLog], int]:
    """分页查询审计日志，支持按 action / user_id 过滤。"""
    stmt = select(AuditLog)
    count_stmt = select(func.count()).select_from(AuditLog)

    if action is not None:
        stmt = stmt.where(AuditLog.action == action)
        count_stmt = count_stmt.where(AuditLog.action == action)
    if user_id is not None:
        stmt = stmt.where(AuditLog.user_id == user_id)
        count_stmt = count_stmt.where(AuditLog.user_id == user_id)

    total = (await db.execute(count_stmt)).scalar_one()

    stmt = stmt.order_by(AuditLog.created_at.desc()).limit(limit).offset(offset)
    items = (await db.execute(stmt)).scalars().all()
    return items, total


async def list_all_users(
    db: AsyncSession,
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[User], int]:
    """管理员视角分页查询用户列表。

    只在 API 层暴露安全字段（id/username/email/created_at），ORM 返回完整 User，
    由 schema 的 from_attributes 自动裁剪——不主动 select password_hash 之外字段。
    """
    total = (
        await db.execute(select(func.count()).select_from(User))
    ).scalar_one()

    stmt = (
        select(User)
        .order_by(User.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    items = (await db.execute(stmt)).scalars().all()
    return items, total


async def get_system_stats(db: AsyncSession) -> dict[str, int]:
    """系统级统计：用户数 / 简历数 / 问答数 / 反馈数 / 求职申请数。"""
    async def _count(model) -> int:
        return (
            await db.execute(select(func.count()).select_from(model))
        ).scalar_one()

    return {
        "total_users": await _count(User),
        "total_resumes": await _count(Resume),
        "total_qa_history": await _count(QAHistory),
        "total_feedback": await _count(UserFeedback),
        "total_job_applications": await _count(JobApplication),
    }


def list_templates() -> list[dict[str, str]]:
    """返回内置模板列表（静态数据，无需 DB）。"""
    return [dict(t) for t in _TEMPLATES]
