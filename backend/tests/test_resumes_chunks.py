"""GET /api/v1/resumes/{id}/chunks 端点测试。

覆盖：
- 401 未登录
- 404 简历不存在或非本人
- 409 简历未就绪（status=processing / failed）
- 409 Chroma collection 不存在（status=ready 但向量未建好）
- 200 成功 + 字段结构正确

TDD 红：端点尚未实现，所有路由调用应返回 404。
TDD 绿：实现端点后所有用例通过。

mock 策略：
- ChromaDB 路径用 patch get_chroma_client + with_chroma
- 归属校验仍走真实 SQLite + Resume 表
"""

from unittest.mock import patch, MagicMock

import pytest
from httpx import AsyncClient

from models.resume import Resume
from tests.conftest import AsyncSessionTest


async def _insert_resume(
    user_id: int,
    *,
    status: str = "ready",
    parsed_text: str = "Python 后端工程师，3 年 FastAPI 开发经验。",
    chunk_count: int = 3,
) -> int:
    """直接插入 Resume 记录，返回 id。"""
    async with AsyncSessionTest() as session:
        resume = Resume(
            user_id=user_id,
            filename="test.pdf",
            file_path="/tmp/test.pdf",
            parsed_text=parsed_text,
            chunk_count=chunk_count,
            status=status,
        )
        session.add(resume)
        await session.commit()
        await session.refresh(resume)
        return resume.id


def _fake_chroma_collection(chunks: list[dict] | None = None):
    """构造假的 Chroma collection，get() 返回指定 chunks。

    chunks=None 表示 collection 不存在（get_collection 抛异常）。
    chunks=[] 表示 collection 存在但为空。
    chunks=[{...}, ...] 表示正常返回。
    """
    if chunks is None:
        # 模拟 collection 不存在
        raise Exception("Collection not found")

    coll = MagicMock()
    # Chroma collection.get 返回 {"documents": [...], "metadatas": [...], "ids": [...]}
    documents = [c["text"] for c in chunks]
    metadatas = [
        {
            "resume_id": c.get("resume_id", 1),
            "chunk_index": c["chunk_index"],
            "section": c["section"],
            "start_char": c["start_char"],
            "end_char": c["end_char"],
        }
        for c in chunks
    ]
    ids = [str(c["chunk_index"]) for c in chunks]
    coll.get.return_value = {
        "documents": documents,
        "metadatas": metadatas,
        "ids": ids,
    }
    return coll


# ── 认证 ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_chunks_without_auth(client: AsyncClient):
    """未登录 → 401。"""
    resp = await client.get("/api/v1/resumes/1/chunks")
    assert resp.status_code == 401


# ── 404 不存在/非本人 ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_chunks_nonexistent_resume(client: AsyncClient, auth_headers: dict):
    """查不存在的 resume_id → 404（归属校验先于 Chroma）。"""
    resp = await client.get(
        "/api/v1/resumes/99999/chunks",
        headers=auth_headers,
    )
    assert resp.status_code == 404


# ── 409 简历未就绪 ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_chunks_processing_resume_returns_409(
    client: AsyncClient, auth_headers: dict, registered_user: dict
):
    """status=processing → 409。"""
    resume_id = await _insert_resume(registered_user["id"], status="processing")
    resp = await client.get(
        f"/api/v1/resumes/{resume_id}/chunks",
        headers=auth_headers,
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_chunks_failed_resume_returns_409(
    client: AsyncClient, auth_headers: dict, registered_user: dict
):
    """status=failed → 409。"""
    resume_id = await _insert_resume(registered_user["id"], status="failed")
    resp = await client.get(
        f"/api/v1/resumes/{resume_id}/chunks",
        headers=auth_headers,
    )
    assert resp.status_code == 409


# ── 409 Chroma collection 不存在 ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_chunks_ready_but_collection_missing_returns_409(
    client: AsyncClient, auth_headers: dict, registered_user: dict
):
    """status=ready 但 Chroma collection 不存在 → 409（数据不一致）。"""
    resume_id = await _insert_resume(registered_user["id"], status="ready")

    # mock get_chroma_client 让 get_collection 抛异常
    fake_client = MagicMock()
    fake_client.get_collection.side_effect = Exception("Collection not found")
    with patch(
        "services.rag.chunks_service.get_chroma_client",
        return_value=fake_client,
    ):
        resp = await client.get(
            f"/api/v1/resumes/{resume_id}/chunks",
            headers=auth_headers,
        )

    assert resp.status_code == 409


# ── 200 成功 ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_chunks_success(client: AsyncClient, auth_headers: dict, registered_user: dict):
    """成功 → 200 + chunks 列表。"""
    resume_id = await _insert_resume(registered_user["id"], status="ready")

    fake_chunks = [
        {
            "resume_id": resume_id,
            "chunk_index": 0,
            "section": "基本信息",
            "text": "姓名：张三，邮箱：zhangsan@example.com",
            "start_char": 0,
            "end_char": 30,
        },
        {
            "resume_id": resume_id,
            "chunk_index": 1,
            "section": "工作经历",
            "text": "A 公司 后端工程师 2022-2024",
            "start_char": 30,
            "end_char": 60,
        },
        {
            "resume_id": resume_id,
            "chunk_index": 2,
            "section": "技能",
            "text": "Python, FastAPI, MySQL",
            "start_char": 60,
            "end_char": 85,
        },
    ]

    fake_client = MagicMock()
    fake_client.get_collection.return_value = _fake_chroma_collection(fake_chunks)
    with patch(
        "services.rag.chunks_service.get_chroma_client",
        return_value=fake_client,
    ):
        resp = await client.get(
            f"/api/v1/resumes/{resume_id}/chunks",
            headers=auth_headers,
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["resume_id"] == resume_id
    assert data["total"] == 3
    assert len(data["chunks"]) == 3

    # 字段结构验证
    c0 = data["chunks"][0]
    assert c0["chunk_index"] == 0
    assert c0["section"] == "基本信息"
    assert "张三" in c0["text"]
    assert c0["start_char"] == 0
    assert c0["end_char"] == 30

    # chunk_index 应该按升序排列
    indices = [c["chunk_index"] for c in data["chunks"]]
    assert indices == [0, 1, 2]


@pytest.mark.asyncio
async def test_chunks_empty_collection_returns_200(
    client: AsyncClient, auth_headers: dict, registered_user: dict
):
    """status=ready 但 Chroma collection 空（无 chunks）→ 200 + total=0。"""
    resume_id = await _insert_resume(registered_user["id"], status="ready", chunk_count=0)

    fake_client = MagicMock()
    fake_client.get_collection.return_value = _fake_chroma_collection(chunks=[])
    with patch(
        "services.rag.chunks_service.get_chroma_client",
        return_value=fake_client,
    ):
        resp = await client.get(
            f"/api/v1/resumes/{resume_id}/chunks",
            headers=auth_headers,
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["resume_id"] == resume_id
    assert data["total"] == 0
    assert data["chunks"] == []
