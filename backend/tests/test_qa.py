"""
问答模块测试：认证校验 / 参数校验 / 历史查询。
实际 RAG 问答需要真实简历数据，放在集成测试中验证。
"""
import pytest
from httpx import AsyncClient


# ── 认证校验 ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_ask_without_auth(client: AsyncClient):
    """未登录提问 → 401。"""
    resp = await client.post("/api/qa/ask", json={
        "resume_id": 1,
        "question": "这个人的学历是什么？",
    })
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_stream_without_auth(client: AsyncClient):
    """未登录流式提问 → 401。"""
    resp = await client.post("/api/qa/ask/stream", json={
        "resume_id": 1,
        "question": "这个人的学历是什么？",
    })
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_history_without_auth(client: AsyncClient):
    """未登录查历史 → 401。"""
    resp = await client.get("/api/qa/history/1")
    assert resp.status_code == 401


# ── 参数校验 ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_ask_empty_question(client: AsyncClient, auth_headers: dict):
    """空问题 → 422。"""
    resp = await client.post("/api/qa/ask", json={
        "resume_id": 1,
        "question": "",
    }, headers=auth_headers)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_ask_whitespace_question(client: AsyncClient, auth_headers: dict):
    """纯空格问题 → 422。"""
    resp = await client.post("/api/qa/ask", json={
        "resume_id": 1,
        "question": "   ",
    }, headers=auth_headers)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_ask_long_question(client: AsyncClient, auth_headers: dict):
    """超长问题（>500字）→ 422。"""
    resp = await client.post("/api/qa/ask", json={
        "resume_id": 1,
        "question": "x" * 501,
    }, headers=auth_headers)
    assert resp.status_code == 422


# ── 历史查询 ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_history_nonexistent_resume(client: AsyncClient, auth_headers: dict):
    """查不存在的简历的历史 → 404。"""
    resp = await client.get("/api/qa/history/99999", headers=auth_headers)
    assert resp.status_code == 404
