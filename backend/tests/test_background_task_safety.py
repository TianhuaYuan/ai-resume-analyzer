"""
Background task 异常信息泄露 + commit 失败被吞。

验证点：
1. 后台任务失败时 status_message 不应包含原始异常字符串（防信息泄露）
2. except 分支应先 rollback 再写 failed 状态（防 session 脏状态导致二次 commit 失败）
3. 二次 commit 失败时应有日志兜底，不能静默吞掉
4. 应使用 logger.exception 保留完整 traceback
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select

from services.resume_service import process_resume_background
from tests.conftest import AsyncSessionTest
from models.resume import Resume
from models.user import User


async def _create_test_user() -> int:
    """创建测试用户，返回 user_id（外键约束开启后必须先有真实用户）。"""
    import uuid as _uuid

    async with AsyncSessionTest() as session:
        user = User(
            username=f"u_{_uuid.uuid4().hex[:8]}",
            email=f"u_{_uuid.uuid4().hex[:8]}@ex.com",
            password_hash="x",
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user.id


async def _insert_processing_resume(user_id: int | None = None) -> int:
    """插入一条 status=processing 的简历，返回 id。"""
    if user_id is None:
        user_id = await _create_test_user()
    async with AsyncSessionTest() as session:
        resume = Resume(
            user_id=user_id,
            filename="test.pdf",
            file_path="/tmp/test.pdf",
            parsed_text="",
            status="processing",
        )
        session.add(resume)
        await session.commit()
        await session.refresh(resume)
        return resume.id


async def _fetch_resume(resume_id: int) -> Resume:
    """从测试 DB 读取简历当前状态。"""
    async with AsyncSessionTest() as session:
        result = await session.execute(select(Resume).where(Resume.id == resume_id))
        return result.scalar_one()


@pytest.mark.asyncio
async def test_background_failure_writes_generic_message_not_exception_detail():
    """后台任务失败时，status_message 应为通用提示，不能包含原始异常字符串。"""
    resume_id = await _insert_processing_resume()

    sensitive_msg = "Connection refused: mysql://root:s3cr3t@10.0.0.1:3306/resume_ai"

    # 用测试 DB 的 session 替换 resume_service 内的 AsyncSessionLocal
    with patch("services.resume_service.parse_resume") as mock_parse, \
         patch("services.resume_service.AsyncSessionLocal", AsyncSessionTest):
        mock_parse.side_effect = RuntimeError(sensitive_msg)

        await process_resume_background(resume_id, "/tmp/test.pdf")

    resume = await _fetch_resume(resume_id)
    assert resume.status == "failed"
    # status_message 不能包含原始异常里的敏感信息
    assert "s3cr3t" not in resume.status_message
    assert "mysql://root" not in resume.status_message
    assert "10.0.0.1" not in resume.status_message


@pytest.mark.asyncio
async def test_background_failure_rolls_back_before_writing_failed_status():
    """except 分支应先 rollback 清理 session 脏状态，再写 failed 状态。"""
    resume_id = await _insert_processing_resume()

    with patch("services.resume_service.parse_resume") as mock_parse, \
         patch("services.resume_service.AsyncSessionLocal") as mock_session_factory:

        # 构造 mock session：execute/commit/rollback 都可控
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)
        mock_session_factory.return_value = mock_session

        mock_parse.side_effect = RuntimeError("parse boom")

        await process_resume_background(resume_id, "/tmp/test.pdf")

        # rollback 必须在第二次 execute + commit 之前被调用
        calls = mock_session.method_calls
        method_names = [c[0] for c in calls]

        assert "rollback" in method_names, "except 分支必须调用 rollback"
        rollback_idx = method_names.index("rollback")
        # rollback 之后应有 execute（写 failed 状态）和 commit
        after_rollback = method_names[rollback_idx + 1:]
        assert "execute" in after_rollback, "rollback 后应执行 update"
        assert "commit" in after_rollback, "rollback 后应执行 commit"


@pytest.mark.asyncio
async def test_background_failure_second_commit_error_is_logged_not_silently_swallowed():
    """二次 commit 失败时，应记录日志而不是静默吞掉。"""
    resume_id = await _insert_processing_resume()

    with patch("services.resume_service.parse_resume") as mock_parse, \
         patch("services.resume_service.AsyncSessionLocal") as mock_session_factory, \
         patch("services.resume_service.logger") as mock_logger:

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)
        mock_session_factory.return_value = mock_session

        mock_parse.side_effect = RuntimeError("parse failed")
        # 第一次 commit（成功分支）抛异常进入 except
        # 第二次 commit（写 failed 状态）也失败
        mock_session.commit.side_effect = [RuntimeError("first commit"), RuntimeError("second commit")]

        # 不应抛异常（二次 commit 失败应被兜底处理）
        await process_resume_background(resume_id, "/tmp/test.pdf")

        # 应该有 logger.exception 调用记录二次 commit 失败
        assert mock_logger.exception.called or mock_logger.error.called, \
            "二次 commit 失败必须有日志记录"


@pytest.mark.asyncio
async def test_background_failure_uses_logger_exception_for_traceback():
    """失败时应使用 logger.exception 记录完整 traceback，而非 logger.error。"""
    resume_id = await _insert_processing_resume()

    with patch("services.resume_service.parse_resume") as mock_parse, \
         patch("services.resume_service.AsyncSessionLocal", AsyncSessionTest), \
         patch("services.resume_service.logger") as mock_logger:

        mock_parse.side_effect = RuntimeError("parse boom")
        mock_logger.exception = MagicMock()
        mock_logger.error = MagicMock()

        await process_resume_background(resume_id, "/tmp/test.pdf")

        # logger.exception 至少被调用一次
        assert mock_logger.exception.called, \
            "应使用 logger.exception 记录完整 traceback，而非 logger.error"
