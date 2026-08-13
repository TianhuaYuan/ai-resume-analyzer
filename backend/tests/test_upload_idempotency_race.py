"""上传幂等并发竞态测试。

验证 (user_id, idempotency_key) UNIQUE 约束 + IntegrityError 兜底逻辑：
当应用层短路检查被并发请求同时通过时，DB 唯一约束让第二个 commit 失败，
端点应回滚、查询已有记录返回 200，并清理本次写入的孤儿文件。

注意：SQLite 测试环境启用 foreign_keys=ON（见 conftest.py），
create_all 会根据模型的 UniqueConstraint 自动创建约束。
"""
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy.exc import IntegrityError

from models.resume import Resume
from tests.conftest import AsyncSessionTest


@pytest.mark.asyncio
async def test_concurrent_idempotent_upload_returns_existing(
    client: AsyncClient, auth_headers: dict, registered_user: dict
):
    """并发竞态：第一个请求成功写入，第二个请求 IntegrityError 后返回已有记录。

    模拟时序：
    - T1: 请求A 短路检查 → None（无记录）→ 写入 → commit 成功
    - T2: 请求B 短路检查 → None（A 还没 commit）→ 写入 → commit 失败 IntegrityError
    - T3: 请求B rollback → 查已有记录 → 找到 A 写入的 → 返回 200 + 清理孤儿文件

    通过 mock _find_resume_by_idempotency_key 的副作用模拟这个时序：
    第 1 次调用（短路检查）返回 None，第 2 次调用（IntegrityError 后）返回已有记录。
    """
    fake_existing = Resume(
        id=999,
        user_id=registered_user["id"],
        filename="first.pdf",
        file_path="/tmp/first.pdf",
        parsed_text="",
        status="processing",
        idempotency_key="concurrent-001",
    )
    fake_file_path = "/tmp/orphan.pdf"

    # 侧效应：第 1 次返回 None（短路检查通过），第 2 次返回已有记录（IntegrityError 后查到）
    find_returns = [None, fake_existing]

    async def fake_find(*args, **kwargs):
        return find_returns.pop(0)

    with patch(
        "api.resumes.resume_service.save_upload_file",
        new_callable=AsyncMock,
        return_value=(fake_file_path, "orphan.pdf"),
    ), patch(
        "api.resumes.resume_service.create_resume_quick",
        new_callable=AsyncMock,
        side_effect=IntegrityError("Duplicate entry", params=None, orig=Exception()),
    ), patch(
        "api.resumes._find_resume_by_idempotency_key",
        new_callable=AsyncMock,
        side_effect=fake_find,
    ), patch("api.resumes.os.remove") as mock_remove:
        resp = await client.post(
            "/api/v1/resumes",
            files={"file": ("orphan.pdf", b"fake", "application/pdf")},
            headers={**auth_headers, "Idempotency-Key": "concurrent-001"},
        )

    # 应返回已有记录，状态码 200（不是 202）
    assert resp.status_code == 200
    assert resp.json()["id"] == 999
    assert resp.json()["filename"] == "first.pdf"
    # 应清理本次写入的孤儿文件
    mock_remove.assert_called_once_with(fake_file_path)


@pytest.mark.asyncio
async def test_integrity_error_with_no_existing_record_reraises(
    client: AsyncClient, auth_headers: dict, registered_user: dict
):
    """罕见场景：IntegrityError 但查不到已有记录（如其他约束冲突）→ 端点转成 HTTPException 500。

    通过 mock _find_resume_by_idempotency_key 始终返回 None，模拟：
    - 短路检查 → None（通过）
    - IntegrityError 后再查 → None（查不到）

    端点应把裸 IntegrityError 转成 HTTPException 500，避免冒泡到 middleware 层
    （BaseHTTPMiddleware 场景下全局 Exception handler 捕获不可靠）。
    """
    with patch(
        "api.resumes.resume_service.save_upload_file",
        new_callable=AsyncMock,
        return_value=("/tmp/orphan.pdf", "orphan.pdf"),
    ), patch(
        "api.resumes.resume_service.create_resume_quick",
        new_callable=AsyncMock,
        side_effect=IntegrityError("Other constraint", params=None, orig=Exception()),
    ), patch(
        "api.resumes._find_resume_by_idempotency_key",
        new_callable=AsyncMock,
        return_value=None,
    ), patch("api.resumes.os.remove"):
        resp = await client.post(
            "/api/v1/resumes",
            files={"file": ("orphan.pdf", b"fake", "application/pdf")},
            headers={**auth_headers, "Idempotency-Key": "nonexistent-key-999"},
        )

    # 端点把 IntegrityError 转成 HTTPException 500，返回用户友好错误
    assert resp.status_code == 500


@pytest.mark.asyncio
async def test_unique_constraint_blocks_duplicate_idempotency_key(
    client: AsyncClient, auth_headers: dict, registered_user: dict
):
    """直接验证 DB 层 UNIQUE 约束生效：同 (user_id, idempotency_key) 插入两次应失败。"""
    from sqlalchemy import insert

    async with AsyncSessionTest() as session:
        # 第一次插入成功
        await session.execute(
            insert(Resume).values(
                user_id=registered_user["id"],
                filename="a.pdf",
                file_path="/tmp/a.pdf",
                parsed_text="",
                status="processing",
                idempotency_key="dup-key-001",
            )
        )
        await session.commit()

        # 第二次插入同 key 应抛 IntegrityError
        with pytest.raises(IntegrityError):
            await session.execute(
                insert(Resume).values(
                    user_id=registered_user["id"],
                    filename="b.pdf",
                    file_path="/tmp/b.pdf",
                    parsed_text="",
                    status="processing",
                    idempotency_key="dup-key-001",
                )
            )
            await session.commit()


@pytest.mark.asyncio
async def test_different_users_can_share_same_idempotency_key(
    client: AsyncClient, auth_headers: dict, registered_user: dict
):
    """不同用户的 idempotency_key 可以相同（复合唯一约束只限制同用户）。"""
    from sqlalchemy import insert

    # 创建第二个用户
    from models.user import User
    async with AsyncSessionTest() as session:
        user2 = User(
            username="other_user",
            email="other@example.com",
            password_hash="x",
        )
        session.add(user2)
        await session.commit()
        await session.refresh(user2)
        user2_id = user2.id

        # 用户1 插入 key="shared-key"
        await session.execute(
            insert(Resume).values(
                user_id=registered_user["id"],
                filename="u1.pdf",
                file_path="/tmp/u1.pdf",
                parsed_text="",
                status="processing",
                idempotency_key="shared-key",
            )
        )
        # 用户2 插入同 key="shared-key" 应成功（不同 user_id）
        await session.execute(
            insert(Resume).values(
                user_id=user2_id,
                filename="u2.pdf",
                file_path="/tmp/u2.pdf",
                parsed_text="",
                status="processing",
                idempotency_key="shared-key",
            )
        )
        await session.commit()  # 应成功


@pytest.mark.asyncio
async def test_null_idempotency_key_allows_multiple_rows(
    client: AsyncClient, auth_headers: dict, registered_user: dict
):
    """idempotency_key=NULL 时允许多条（标准 SQL 多个 NULL 不冲突）。"""
    from sqlalchemy import insert

    async with AsyncSessionTest() as session:
        # 插入两条 idempotency_key=NULL 的 resume，都应成功
        await session.execute(
            insert(Resume).values(
                user_id=registered_user["id"],
                filename="a.pdf",
                file_path="/tmp/a.pdf",
                parsed_text="",
                status="processing",
                idempotency_key=None,
            )
        )
        await session.execute(
            insert(Resume).values(
                user_id=registered_user["id"],
                filename="b.pdf",
                file_path="/tmp/b.pdf",
                parsed_text="",
                status="processing",
                idempotency_key=None,
            )
        )
        await session.commit()  # 应成功
