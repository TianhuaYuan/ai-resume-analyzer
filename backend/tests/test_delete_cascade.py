"""简历删除级联测试。

验证 delete_resume 完整执行四层清理：
1. MySQL：resume 行删除后，qa_history 通过外键 CASCADE 自动清理
2. Embedding 内存缓存：clear_resume(resume_id) 被调用
3. ChromaDB 向量：clear_resume_vectors(resume_id) 被调用
4. 文件系统：os.remove(file_path) 删除上传的原始文件

边界：
- 删除不存在 resume → 404
- 删除他人 resume → 404（归属校验，不泄露存在性）
- 文件已丢失时不抛异常（os.remove 失败仅记日志）
"""
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from core import cache as embedding_cache
from models.qa_history import QAHistory
from models.resume import Resume
from models.user import User
from services.resume_service import delete_resume
from tests.conftest import AsyncSessionTest


async def _create_second_user(username: str = "other_user", email: str = "other@example.com") -> int:
    """直接在 DB 插入一个用户（绕过 API），返回 user_id。"""
    async with AsyncSessionTest() as session:
        user = User(
            username=username,
            email=email,
            password_hash="fake_hash",
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user.id


async def _insert_resume_with_qa(
    user_id: int, file_path: str = "/tmp/test_resume.pdf"
) -> tuple[int, int]:
    """插入一份简历 + 两条问答历史，返回 (resume_id, qa_id_list)。"""
    async with AsyncSessionTest() as session:
        resume = Resume(
            user_id=user_id,
            filename="test.pdf",
            file_path=file_path,
            parsed_text="张三的简历",
            chunk_count=2,
            status="ready",
        )
        session.add(resume)
        await session.commit()
        await session.refresh(resume)

        qa1 = QAHistory(
            user_id=user_id,
            resume_id=resume.id,
            question="学历是什么？",
            answer="本科",
            sources=[{"chunk_id": 0, "text": "本科", "section": "edu"}],
        )
        qa2 = QAHistory(
            user_id=user_id,
            resume_id=resume.id,
            question="工作经验？",
            answer="3年",
            sources=[{"chunk_id": 1, "text": "3年", "section": "exp"}],
        )
        session.add_all([qa1, qa2])
        await session.commit()
        await session.refresh(qa1)
        await session.refresh(qa2)
        return resume.id, [qa1.id, qa2.id]


async def _count_qa_for_resume(resume_id: int) -> int:
    async with AsyncSessionTest() as session:
        result = await session.execute(
            select(QAHistory).where(QAHistory.resume_id == resume_id)
        )
        return len(result.scalars().all())


async def _resume_exists(resume_id: int) -> bool:
    async with AsyncSessionTest() as session:
        result = await session.execute(select(Resume).where(Resume.id == resume_id))
        return result.scalar_one_or_none() is not None


# ---------------- MySQL CASCADE ----------------


@pytest.mark.asyncio
async def test_delete_resume_cascades_to_qa_history(registered_user: dict):
    """删除 resume 后，关联的 qa_history 应通过外键 CASCADE 自动删除。"""
    resume_id, qa_ids = await _insert_resume_with_qa(registered_user["id"])

    async with AsyncSessionTest() as session:
        await delete_resume(session, resume_id, registered_user["id"])

    assert not await _resume_exists(resume_id), "resume 行应已删除"
    assert await _count_qa_for_resume(resume_id) == 0, "qa_history 应被 CASCADE 清理"


@pytest.mark.asyncio
async def test_delete_resume_only_cascades_own_qa_history(
    registered_user: dict,
):
    """删除 resume A 不应影响 resume B 的 qa_history。"""
    resume_a_id, _ = await _insert_resume_with_qa(
        registered_user["id"], file_path="/tmp/a.pdf"
    )
    resume_b_id, qa_b_ids = await _insert_resume_with_qa(
        registered_user["id"], file_path="/tmp/b.pdf"
    )

    async with AsyncSessionTest() as session:
        await delete_resume(session, resume_a_id, registered_user["id"])

    assert not await _resume_exists(resume_a_id)
    assert await _resume_exists(resume_b_id), "resume B 不应受影响"
    assert await _count_qa_for_resume(resume_b_id) == len(qa_b_ids)


# ---------------- Embedding 缓存 ----------------


@pytest.mark.asyncio
async def test_delete_resume_clears_embedding_cache(registered_user: dict):
    """delete_resume 应调用 embedding_cache.clear_resume(resume_id)。"""
    resume_id, _ = await _insert_resume_with_qa(registered_user["id"])

    with patch(
        "services.resume_service.embedding_cache.clear_resume",
        new_callable=AsyncMock,
        return_value=3,
    ) as mock_clear_cache, patch(
        "services.resume_service.clear_resume_vectors", new_callable=AsyncMock
    ), patch("services.resume_service.os.remove"):
        async with AsyncSessionTest() as session:
            await delete_resume(session, resume_id, registered_user["id"])

    mock_clear_cache.assert_awaited_once_with(resume_id)


@pytest.mark.asyncio
async def test_delete_resume_clears_real_embedding_cache(registered_user: dict):
    """集成场景：真实 cache 模块应在删除后不再保留该 resume 的 embedding 索引。"""
    resume_id, _ = await _insert_resume_with_qa(registered_user["id"])

    # 灌入 2 条 embedding，绑定到该 resume
    await embedding_cache.set_embedding("片段A", [0.1, 0.2], resume_id=resume_id)
    await embedding_cache.set_embedding("片段B", [0.3, 0.4], resume_id=resume_id)

    with patch(
        "services.resume_service.clear_resume_vectors", new_callable=AsyncMock
    ), patch("services.resume_service.os.remove"):
        async with AsyncSessionTest() as session:
            await delete_resume(session, resume_id, registered_user["id"])

    # 真实 clear_resume 应已清理掉两条
    cleared = await embedding_cache.clear_resume(resume_id)
    assert cleared == 0, "delete_resume 应已清空 embedding 缓存，二次清理应返回 0"


# ---------------- ChromaDB ----------------


@pytest.mark.asyncio
async def test_delete_resume_clears_chroma_vectors(registered_user: dict):
    """delete_resume 应调用 clear_resume_vectors(resume_id) 清理 Chroma + BM25。"""
    resume_id, _ = await _insert_resume_with_qa(registered_user["id"])

    with patch(
        "services.resume_service.clear_resume_vectors", new_callable=AsyncMock
    ) as mock_clear_vectors, patch(
        "services.resume_service.embedding_cache.clear_resume",
        new_callable=AsyncMock,
        return_value=0,
    ), patch("services.resume_service.os.remove"):
        async with AsyncSessionTest() as session:
            await delete_resume(session, resume_id, registered_user["id"])

    mock_clear_vectors.assert_awaited_once_with(registered_user["id"], resume_id)


@pytest.mark.asyncio
async def test_delete_resume_clears_redis_analysis_cache(registered_user: dict):
    """delete_resume 应调用 invalidate_resume_cache 清 Redis 分析缓存（4 种类型）。"""
    resume_id, _ = await _insert_resume_with_qa(registered_user["id"])

    with patch(
        "services.resume_service.invalidate_resume_cache", new_callable=AsyncMock
    ) as mock_invalidate, patch(
        "services.resume_service.clear_resume_vectors", new_callable=AsyncMock
    ), patch(
        "services.resume_service.embedding_cache.clear_resume",
        new_callable=AsyncMock,
        return_value=0,
    ), patch("services.resume_service.os.remove"):
        async with AsyncSessionTest() as session:
            await delete_resume(session, resume_id, registered_user["id"])

    mock_invalidate.assert_awaited_once_with(resume_id)


# ---------------- 文件系统 ----------------


@pytest.mark.asyncio
async def test_delete_resume_removes_uploaded_file(tmp_path, registered_user: dict):
    """delete_resume 应删除上传的原始文件。"""
    # 构造一个真实文件，验证 os.remove 被实际调用
    file_path = tmp_path / "resume.pdf"
    file_path.write_bytes(b"fake pdf content")

    resume_id, _ = await _insert_resume_with_qa(
        registered_user["id"], file_path=str(file_path)
    )

    with patch(
        "services.resume_service.clear_resume_vectors", new_callable=AsyncMock
    ), patch(
        "services.resume_service.embedding_cache.clear_resume",
        new_callable=AsyncMock,
        return_value=0,
    ):
        async with AsyncSessionTest() as session:
            await delete_resume(session, resume_id, registered_user["id"])

    assert not file_path.exists(), "上传的原始文件应被删除"


@pytest.mark.asyncio
async def test_delete_resume_swallows_missing_file(registered_user: dict):
    """文件已不存在时，delete_resume 不应抛异常（仅记 warning 日志）。"""
    resume_id, _ = await _insert_resume_with_qa(
        registered_user["id"], file_path="/tmp/already_deleted.pdf"
    )

    with patch(
        "services.resume_service.clear_resume_vectors", new_callable=AsyncMock
    ), patch(
        "services.resume_service.embedding_cache.clear_resume",
        new_callable=AsyncMock,
        return_value=0,
    ), patch("services.resume_service.os.remove") as mock_remove:
        mock_remove.side_effect = FileNotFoundError("already gone")
        # 不应抛异常
        async with AsyncSessionTest() as session:
            await delete_resume(session, resume_id, registered_user["id"])

    mock_remove.assert_called_once_with("/tmp/already_deleted.pdf")


# ---------------- 权限与边界 ----------------


@pytest.mark.asyncio
async def test_delete_resume_not_found_raises_404(registered_user: dict):
    """删除不存在的 resume 应抛 404。"""
    from fastapi import HTTPException

    async with AsyncSessionTest() as session:
        with pytest.raises(HTTPException) as exc:
            await delete_resume(session, 99999, registered_user["id"])

    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_delete_resume_owned_by_other_user_returns_404(registered_user: dict):
    """删除他人 resume 应返回 404（不泄露存在性）。"""
    # 创建真实的第二个用户，避免外键约束失败
    other_user_id = await _create_second_user()
    resume_id, _ = await _insert_resume_with_qa(user_id=other_user_id)

    from fastapi import HTTPException

    async with AsyncSessionTest() as session:
        with pytest.raises(HTTPException) as exc:
            await delete_resume(session, resume_id, registered_user["id"])

    assert exc.value.status_code == 404
    # resume 应仍然存在（未被误删）
    assert await _resume_exists(resume_id), "他人 resume 不应被删除"


# ---------------- API 端点集成 ----------------


@pytest.mark.asyncio
async def test_delete_resume_api_returns_204(
    client: AsyncClient, auth_headers: dict, registered_user: dict
):
    """DELETE /api/v1/resumes/{id} 成功应返回 204。"""
    resume_id, _ = await _insert_resume_with_qa(registered_user["id"])

    with patch(
        "services.resume_service.clear_resume_vectors", new_callable=AsyncMock
    ), patch(
        "services.resume_service.embedding_cache.clear_resume",
        new_callable=AsyncMock,
        return_value=0,
    ), patch("services.resume_service.os.remove"):
        resp = await client.delete(f"/api/v1/resumes/{resume_id}", headers=auth_headers)

    assert resp.status_code == 204


@pytest.mark.asyncio
async def test_delete_resume_succeeds_when_external_cleanup_fails(registered_user: dict):
    """外部资源清理失败不应阻塞已提交的 DB 删除，后续可后台重试清理。"""
    resume_id, _ = await _insert_resume_with_qa(registered_user["id"])

    with patch(
        "services.resume_service.clear_resume_vectors",
        new_callable=AsyncMock,
        side_effect=Exception("ChromaDB 不可用"),
    ):
        async with AsyncSessionTest() as session:
            await delete_resume(session, resume_id, registered_user["id"])

    assert not await _resume_exists(resume_id)


@pytest.mark.asyncio
async def test_delete_resume_api_not_found_returns_404(
    client: AsyncClient, auth_headers: dict
):
    """DELETE 不存在的 resume 应返回 404。"""
    resp = await client.delete("/api/v1/resumes/99999", headers=auth_headers)
    assert resp.status_code == 404
