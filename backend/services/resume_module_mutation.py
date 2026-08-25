"""ResumeModule 写入的统一原子 claim 与 locking current read。"""

from sqlalchemy import select, update
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from models.resume import Resume
from models.resume_module import ResumeModule


class ResumeModuleConflictError(Exception):
    """模块内容已被其他事务修改。"""


def _is_lock_conflict(error: OperationalError) -> bool:
    """仅识别 SQLite busy/locked 与 MySQL lock timeout/deadlock。"""
    original = error.orig
    message = str(original or error).lower()
    if "locked" in message or "busy" in message:
        return True
    errno = getattr(original, "errno", None)
    if errno is None:
        for arg in getattr(original, "args", ()):
            if isinstance(arg, int):
                errno = arg
                break
            if isinstance(arg, str) and arg.isdigit():
                errno = int(arg)
                break
    return errno in (1205, 1213)


async def lock_resume_for_module_mutation(
    session: AsyncSession,
    user_id: int,
    resume_id: int,
    expected_revision: int | None = None,
) -> Resume | None:
    """事务开头原子 claim：revision +1；失败统一为领域冲突。"""
    if expected_revision is not None:
        if not isinstance(expected_revision, int) or isinstance(expected_revision, bool):
            raise ResumeModuleConflictError("期望模块修订号必须为整数。")
    statement = (
        update(Resume)
        .where(Resume.id == resume_id, Resume.user_id == user_id)
        .values(module_revision=Resume.module_revision + 1)
    )
    if expected_revision is not None:
        statement = statement.where(Resume.module_revision == expected_revision)
    try:
        result = await session.execute(statement)
    except OperationalError as e:
        if _is_lock_conflict(e):
            raise ResumeModuleConflictError("简历模块正在被其他事务修改，请稍后重试。") from e
        raise
    if result.rowcount != 1:
        if expected_revision is not None:
            raise ResumeModuleConflictError("简历模块版本冲突，请刷新后重试。")
        return None
    locked = await session.execute(
        select(Resume)
        .where(Resume.id == resume_id, Resume.user_id == user_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return locked.scalar_one()


async def load_resume_modules_for_mutation(
    session: AsyncSession, resume_id: int
) -> list[ResumeModule]:
    """claim 后读取当前模块；禁止复用 claim 前 identity-map 快照。"""
    result = await session.execute(
        select(ResumeModule)
        .where(ResumeModule.resume_id == resume_id)
        .order_by(ResumeModule.sort_order, ResumeModule.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return list(result.scalars().all())
