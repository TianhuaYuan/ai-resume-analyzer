"""process_resume_background 成功路径测试。

已有的 test_background_task_safety.py 只测失败路径（异常 / 信息泄露 / 二次 commit 失败），
这里补成功路径：解析成功 → 分块 → 向量化 → 状态变 ready。

关键验证点：
1. 成功时 status 从 processing → ready
2. parsed_text 被写入
3. chunk_count 被写入
4. 不残留 failed 状态
"""

from unittest.mock import patch

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
async def test_background_success_marks_resume_ready():
    """成功路径：解析成功 → 状态变 ready + parsed_text + chunk_count 写入。"""
    resume_id = await _insert_processing_resume()

    fake_parsed_text = "张三\nPython 工程师\n3年经验"

    # 用测试 DB session 替换生产 AsyncSessionLocal
    with patch("services.resume_service.parse_resume", return_value=fake_parsed_text), \
         patch("services.resume_service.AsyncSessionLocal", AsyncSessionTest):
        await process_resume_background(resume_id, "/tmp/test.pdf")

    resume = await _fetch_resume(resume_id)
    assert resume.status == "ready"
    assert resume.parsed_text == fake_parsed_text
    assert resume.chunk_count == 0  # 懒索引：上传后未建索引
    # 成功完成时 status_message 为完成提示（实现语义：状态迁移同步更新消息）
    assert resume.status_message in {"解析完成", "文本已读取，表单识别待重试"}


@pytest.mark.asyncio
async def test_background_success_does_not_set_failed_status():
    """成功路径：不应残留 failed 状态。"""
    resume_id = await _insert_processing_resume()

    with patch("services.resume_service.parse_resume", return_value="内容"), \
         patch("services.resume_service.AsyncSessionLocal", AsyncSessionTest):
        await process_resume_background(resume_id, "/tmp/test.pdf")

    resume = await _fetch_resume(resume_id)
    assert resume.status != "failed"


@pytest.mark.asyncio
async def test_background_success_calls_parse_and_process_in_order():
    """成功路径：parse_resume 被调用（后台已不建索引，懒索引推迟到首次消费，见 T4/D3）。"""
    resume_id = await _insert_processing_resume()

    call_order: list[str] = []

    def fake_parse(path: str) -> str:
        call_order.append("parse")
        assert path == "/tmp/test.pdf"
        return "内容"

    with patch("services.resume_service.parse_resume", side_effect=fake_parse), \
         patch("services.resume_service.AsyncSessionLocal", AsyncSessionTest):
        await process_resume_background(resume_id, "/tmp/test.pdf")

    assert call_order == ["parse"]


@pytest.mark.asyncio
async def test_background_success_with_zero_chunks():
    """边界：解析成功但内容为空也应标记为 ready（懒索引下 chunk_count 恒为 0，不误判失败）。"""
    resume_id = await _insert_processing_resume()

    with patch("services.resume_service.parse_resume", return_value="空内容"), \
         patch("services.resume_service.AsyncSessionLocal", AsyncSessionTest):
        await process_resume_background(resume_id, "/tmp/test.pdf")

    resume = await _fetch_resume(resume_id)
    # chunk_count=0 不是失败，仍应标记为 ready
    assert resume.status == "ready"
    assert resume.chunk_count == 0
