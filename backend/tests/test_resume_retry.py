"""
P1-13：后台处理无容错 — 进程崩溃后简历永久卡 processing。
P1-24：简历处理失败后无法手动重试。

验证点：
P1-13:
  - 启动时检测到 status=processing 的简历应标记为 failed（因后台任务已丢失）

P1-24:
  - POST /resumes/{id}/retry 对 failed 简历应重新触发处理
  - POST /resumes/{id}/retry 对 ready 简历应返回 409
  - POST /resumes/{id}/retry 对 processing 简历应返回 409
  - POST /resumes/{id}/retry 对不存在简历应返回 404
"""

from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from models.resume import Resume
from models.user import User
from services.resume_service import recover_stuck_resumes
from tests.conftest import AsyncSessionTest


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


async def _insert_resume(
    user_id: int,
    *,
    status: str = "processing",
    file_path: str = "/tmp/test.pdf",
) -> int:
    """直接插入 Resume 记录，返回 id。"""
    async with AsyncSessionTest() as session:
        resume = Resume(
            user_id=user_id,
            filename="test.pdf",
            file_path=file_path,
            parsed_text="",
            status=status,
        )
        session.add(resume)
        await session.commit()
        await session.refresh(resume)
        return resume.id


# ── P1-13：启动恢复 ──────────────────────────────────────


@pytest.mark.asyncio
async def test_recover_stuck_resumes_marks_processing_as_failed():
    """启动时 status=processing 的简历应被标记为 failed。"""
    user_id = await _create_test_user()
    resume_id = await _insert_resume(user_id=user_id, status="processing")

    # recover_stuck_resumes 内部用 AsyncSessionLocal，测试中替换为测试 DB
    with patch("services.resume_service.AsyncSessionLocal", AsyncSessionTest):
        await recover_stuck_resumes()

    async with AsyncSessionTest() as session:
        result = await session.execute(select(Resume).where(Resume.id == resume_id))
        resume = result.scalar_one()
        assert resume.status == "failed"
        assert "处理失败" in resume.status_message or "异常中断" in resume.status_message


@pytest.mark.asyncio
async def test_recover_stuck_resumes_does_not_touch_ready():
    """ready 状态的简历不应被启动恢复影响。"""
    user_id = await _create_test_user()
    resume_id = await _insert_resume(user_id=user_id, status="ready", file_path="/tmp/ready.pdf")

    with patch("services.resume_service.AsyncSessionLocal", AsyncSessionTest):
        await recover_stuck_resumes()

    async with AsyncSessionTest() as session:
        result = await session.execute(select(Resume).where(Resume.id == resume_id))
        resume = result.scalar_one()
        assert resume.status == "ready"


@pytest.mark.asyncio
async def test_recover_stuck_resumes_does_not_touch_failed():
    """failed 状态的简历不应被启动恢复影响。"""
    user_id = await _create_test_user()
    resume_id = await _insert_resume(user_id=user_id, status="failed")

    await recover_stuck_resumes()

    async with AsyncSessionTest() as session:
        result = await session.execute(select(Resume).where(Resume.id == resume_id))
        resume = result.scalar_one()
        assert resume.status == "failed"


# ── P1-24：手动重试 ──────────────────────────────────────


@pytest.mark.asyncio
async def test_retry_failed_resume_re_triggers_processing(
    client: AsyncClient, auth_headers: dict, registered_user: dict
):
    """POST /resumes/{id}/retry 对 failed 简历应重新触发处理，返回 202。"""
    resume_id = await _insert_resume(registered_user["id"], status="failed")

    with patch("services.resume_service.process_resume_background", new_callable=AsyncMock) as mock_bg:
        resp = await client.post(f"/api/v1/resumes/{resume_id}/retry", headers=auth_headers)

    assert resp.status_code == 202
    # 后台任务应被调用
    mock_bg.assert_called_once()
    # 数据库中 status 应回到 processing
    async with AsyncSessionTest() as session:
        result = await session.execute(select(Resume).where(Resume.id == resume_id))
        resume = result.scalar_one()
        assert resume.status == "processing"


@pytest.mark.asyncio
async def test_retry_ready_resume_returns_409(
    client: AsyncClient, auth_headers: dict, registered_user: dict
):
    """POST /resumes/{id}/retry 对 ready 简历应返回 409。"""
    resume_id = await _insert_resume(registered_user["id"], status="ready")

    resp = await client.post(f"/api/v1/resumes/{resume_id}/retry", headers=auth_headers)

    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_retry_processing_resume_returns_409(
    client: AsyncClient, auth_headers: dict, registered_user: dict
):
    """POST /resumes/{id}/retry 对 processing 简历应返回 409。"""
    resume_id = await _insert_resume(registered_user["id"], status="processing")

    resp = await client.post(f"/api/v1/resumes/{resume_id}/retry", headers=auth_headers)

    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_retry_nonexistent_resume_returns_404(
    client: AsyncClient, auth_headers: dict
):
    """POST /resumes/{id}/retry 对不存在简历应返回 404。"""
    resp = await client.post("/api/v1/resumes/99999/retry", headers=auth_headers)
    assert resp.status_code == 404
