"""统一 ResumeModule mutation claim 的并发与查询语义。"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.exc import OperationalError

from models.resume import Resume
from services.resume_module_mutation import (
    ResumeModuleConflictError,
    load_resume_modules_for_mutation,
    lock_resume_for_module_mutation,
)
from tests.conftest import AsyncSessionTest


async def test_same_revision_two_sessions_only_one_claims(registered_user):
    async with AsyncSessionTest() as setup:
        resume = Resume(
            user_id=registered_user["id"],
            filename="claim-test",
            file_path="",
            parsed_text="",
            status="draft",
            source="builder",
            module_revision=0,
        )
        setup.add(resume)
        await setup.commit()
        resume_id = resume.id

    start = asyncio.Event()

    async def contender() -> bool:
        async with AsyncSessionTest() as session:
            await start.wait()
            try:
                await lock_resume_for_module_mutation(
                    session,
                    registered_user["id"],
                    resume_id,
                    expected_revision=0,
                )
                await session.commit()
                return True
            except ResumeModuleConflictError:
                await session.rollback()
                return False

    tasks = [asyncio.create_task(contender()), asyncio.create_task(contender())]
    start.set()
    assert sorted(await asyncio.gather(*tasks)) == [False, True]

    async with AsyncSessionTest() as verify:
        stored = await verify.get(Resume, resume_id)
        assert stored.module_revision == 1


async def test_database_locked_is_domain_conflict():
    session = MagicMock()
    session.execute = AsyncMock(
        side_effect=OperationalError("UPDATE resumes", {}, Exception("database is locked"))
    )

    with pytest.raises(ResumeModuleConflictError, match="其他事务"):
        await lock_resume_for_module_mutation(session, 1, 1, expected_revision=0)


async def test_mysql_deadlock_is_domain_conflict():
    original = Exception(1213, "Deadlock found when trying to get lock")
    session = MagicMock()
    session.execute = AsyncMock(
        side_effect=OperationalError("UPDATE resumes", {}, original)
    )

    with pytest.raises(ResumeModuleConflictError, match="其他事务"):
        await lock_resume_for_module_mutation(session, 1, 1, expected_revision=0)


async def test_non_competition_operational_error_propagates():
    error = OperationalError("UPDATE resumes", {}, Exception("connection lost"))
    session = MagicMock()
    session.execute = AsyncMock(side_effect=error)

    with pytest.raises(OperationalError) as exc_info:
        await lock_resume_for_module_mutation(session, 1, 1, expected_revision=0)
    assert exc_info.value is error


async def test_module_mutation_read_uses_locking_current_read():
    result = MagicMock()
    result.scalars.return_value.all.return_value = []
    session = MagicMock()
    session.execute = AsyncMock(return_value=result)

    await load_resume_modules_for_mutation(session, 1)

    statement = session.execute.await_args.args[0]
    assert statement._for_update_arg is not None
    assert statement.get_execution_options()["populate_existing"] is True
