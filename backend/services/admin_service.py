"""T34: 管理员后台服务层。

提供审计日志查询、用户列表（脱敏）、系统级统计、模板列表等能力。
所有函数均为 async，接收 AsyncSession（统计/列表/审计日志），模板列表为静态数据无需 DB。
"""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.audit_log import AuditLog
from models.qa_history import QAHistory
from models.resume import Resume
from models.user import User
from models.user_feedback import UserFeedback

# 18 套内置模板（与 backend/templates/*.html 对齐，由 generate-templates 生成）
# id = 文件名（template_id），name/description 为管理员后台展示用
_TEMPLATES: list[dict[str, str]] = [
    {"id": "default", "name": "经典蓝", "description": "单栏百搭，通用性强（默认模板 + 兜底）"},
    {"id": "azurill", "name": "深蓝侧栏", "description": "深蓝侧栏 + 主栏时间轴，现代专业"},
    {"id": "teal", "name": "青绿侧栏", "description": "青绿侧栏，技术岗清新风"},
    {"id": "gengar", "name": "暗夜紫", "description": "深色侧栏 + 暗底主栏，紫强调"},
    {"id": "slate", "name": "深板岩侧栏", "description": "深灰侧栏 + 蓝色强调，沉稳技术风"},
    {"id": "orange", "name": "活力橙双栏", "description": "橙色侧栏双栏，活泼自信"},
    {"id": "chikorita", "name": "清新绿侧栏", "description": "清新绿侧栏，自然亲和"},
    {"id": "golden-elegant", "name": "琥珀深侧栏", "description": "琥珀强调 + 深灰侧栏，优雅高端"},
    {"id": "executive", "name": "深蓝头带", "description": "深蓝头带 + 职业时间轴，商务正式"},
    {"id": "ditto", "name": "卡片现代", "description": "浅灰底 + 白卡片模块，现代轻盈"},
    {"id": "timeline-pro", "name": "青绿时间轴", "description": "单栏时间轴 + 节点圆点，突出职业轨迹"},
    {"id": "serif", "name": "衬线留白", "description": "衬线字体 + 大留白，Premium 质感"},
    {"id": "skills-first", "name": "技能聚焦", "description": "勃艮第强调 + 技能胶囊，成果导向"},
    {"id": "classic", "name": "经典衬线", "description": "衬线经典排版，学术/正式岗位首选"},
    {"id": "red-accent", "name": "红色强调", "description": "红色强调线 + 干净单栏，醒目现代"},
    {"id": "product-ops", "name": "产品运营青绿", "description": "青绿聚焦 + 简洁单栏，产品/运营岗"},
    {"id": "cn-formal", "name": "中文正装", "description": "中文正式单栏，适合国企/事业单位"},
    {"id": "compact-cn", "name": "中文紧凑", "description": "中文紧凑单栏，一页纸信息密度高"},
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
    }


def list_templates() -> list[dict[str, str]]:
    """返回内置模板列表（静态数据，无需 DB）。"""
    return [dict(t) for t in _TEMPLATES]
