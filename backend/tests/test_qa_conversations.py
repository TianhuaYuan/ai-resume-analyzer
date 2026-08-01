"""对话会话测试：多对话 CRUD + 按会话过滤历史。

覆盖：
- GET   /api/v1/qa/conversations/{resume_id}  列出简历下所有对话
- POST  /api/v1/qa/conversations/{resume_id}  创建新对话
- PUT   /api/v1/qa/conversations/{conversation_id}  重命名对话
- DELETE /api/v1/qa/conversations/{conversation_id} 删除对话及其问答
- GET   /api/v1/qa/history/{resume_id}?conversation_id=  按会话过滤历史
"""

import pytest
from httpx import AsyncClient

from models.qa_conversation import QAConversation
from models.qa_history import QAHistory
from models.resume import Resume
from tests.conftest import AsyncSessionTest


async def _insert_resume(user_id: int) -> int:
    async with AsyncSessionTest() as session:
        resume = Resume(
            user_id=user_id,
            filename="test.pdf",
            file_path="/tmp/test.pdf",
            parsed_text="Python 后端工程师",
            chunk_count=3,
            status="ready",
        )
        session.add(resume)
        await session.commit()
        await session.refresh(resume)
        return resume.id


async def _insert_conversation(user_id: int, resume_id: int, title: str = "新对话") -> int:
    async with AsyncSessionTest() as session:
        conv = QAConversation(
            user_id=user_id,
            resume_id=resume_id,
            title=title,
        )
        session.add(conv)
        await session.commit()
        await session.refresh(conv)
        return conv.id


async def _insert_qa(user_id: int, resume_id: int, conversation_id: int | None) -> int:
    async with AsyncSessionTest() as session:
        qa = QAHistory(
            user_id=user_id,
            resume_id=resume_id,
            conversation_id=conversation_id,
            question="测试问题",
            answer="测试答案",
            sources=[],
        )
        session.add(qa)
        await session.commit()
        await session.refresh(qa)
        return qa.id


# ── 认证校验 ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_conversations_without_auth(client: AsyncClient):
    resp = await client.get("/api/v1/qa/conversations/1")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_create_conversation_without_auth(client: AsyncClient):
    resp = await client.post("/api/v1/qa/conversations/1", json={})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_delete_conversation_without_auth(client: AsyncClient):
    resp = await client.delete("/api/v1/qa/conversations/1")
    assert resp.status_code == 401


# ── 会话 CRUD ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_and_list_conversation(
    client: AsyncClient, auth_headers: dict, registered_user: dict
):
    resume_id = await _insert_resume(registered_user["id"])

    # 创建两个对话
    resp = await client.post(
        f"/api/v1/qa/conversations/{resume_id}",
        json={"title": "亮点分析"},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    assert resp.json()["title"] == "亮点分析"
    assert resp.json()["message_count"] == 0

    await client.post(
        f"/api/v1/qa/conversations/{resume_id}",
        json={},
        headers=auth_headers,
    )

    # 列表
    resp = await client.get(
        f"/api/v1/qa/conversations/{resume_id}", headers=auth_headers
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 2
    # 默认标题
    titles = {c["title"] for c in data["items"]}
    assert "新对话" in titles


@pytest.mark.asyncio
async def test_create_conversation_title_too_long(client: AsyncClient, auth_headers: dict, registered_user: dict):
    resume_id = await _insert_resume(registered_user["id"])
    resp = await client.post(
        f"/api/v1/qa/conversations/{resume_id}",
        json={"title": "x" * 101},
        headers=auth_headers,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_conversation_nonexistent_resume(client: AsyncClient, auth_headers: dict):
    resp = await client.post(
        "/api/v1/qa/conversations/99999",
        json={},
        headers=auth_headers,
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_rename_conversation(client: AsyncClient, auth_headers: dict, registered_user: dict):
    resume_id = await _insert_resume(registered_user["id"])
    conv_id = await _insert_conversation(registered_user["id"], resume_id, "旧标题")

    resp = await client.put(
        f"/api/v1/qa/conversations/{conv_id}",
        json={"title": "新标题"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["title"] == "新标题"


@pytest.mark.asyncio
async def test_rename_conversation_other_user(client: AsyncClient, auth_headers: dict, registered_user: dict):
    """重命名别人的对话 → 404（归属隔离）。"""
    resume_id = await _insert_resume(registered_user["id"])
    conv_id = await _insert_conversation(registered_user["id"], resume_id, "别人的")

    # 用另一个用户
    other_user = {
        "username": "other",
        "email": "other@example.com",
        "password": "Test1234!",
        "password_confirm": "Test1234!",
    }
    await client.post("/api/v1/auth/send-code", json={"email": other_user["email"]})
    from services.verification_service import _in_memory_codes, _CODE_KEY_PREFIX
    key = f"{_CODE_KEY_PREFIX}{other_user['email']}"
    code_entry = _in_memory_codes.get(key)
    code = code_entry["code"] if code_entry else "123456"
    await client.post(
        "/api/v1/auth/register",
        json={**other_user, "verification_code": code},
    )
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": other_user["email"], "password": other_user["password"]},
    )
    other_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    resp = await client.put(
        f"/api/v1/qa/conversations/{conv_id}",
        json={"title": "篡改"},
        headers=other_headers,
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_conversation_cascades_qa(
    client: AsyncClient, auth_headers: dict, registered_user: dict
):
    resume_id = await _insert_resume(registered_user["id"])
    conv_id = await _insert_conversation(registered_user["id"], resume_id)
    qa_id = await _insert_qa(registered_user["id"], resume_id, conv_id)

    resp = await client.delete(
        f"/api/v1/qa/conversations/{conv_id}", headers=auth_headers
    )
    assert resp.status_code == 200
    assert resp.json()["deleted_count"] == 1

    # 对话和其问答都已被删除
    resp = await client.get(
        f"/api/v1/qa/conversations/{resume_id}", headers=auth_headers
    )
    assert resp.json()["total"] == 0
    resp = await client.get(
        f"/api/v1/qa/history/{resume_id}", headers=auth_headers
    )
    assert resp.json()["total"] == 0


@pytest.mark.asyncio
async def test_delete_conversation_other_user(client: AsyncClient, auth_headers: dict, registered_user: dict):
    resume_id = await _insert_resume(registered_user["id"])
    conv_id = await _insert_conversation(registered_user["id"], resume_id)
    resp = await client.delete(
        f"/api/v1/qa/conversations/{conv_id}",
        headers=auth_headers,
    )
    assert resp.status_code == 200


# ── 按会话过滤历史 ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_history_filtered_by_conversation(
    client: AsyncClient, auth_headers: dict, registered_user: dict
):
    resume_id = await _insert_resume(registered_user["id"])
    conv_a = await _insert_conversation(registered_user["id"], resume_id, "A")
    conv_b = await _insert_conversation(registered_user["id"], resume_id, "B")
    await _insert_qa(registered_user["id"], resume_id, conv_a)
    await _insert_qa(registered_user["id"], resume_id, conv_b)
    # 无会话归属的历史（老数据兼容）
    await _insert_qa(registered_user["id"], resume_id, None)

    # 全部 → 3 条
    resp = await client.get(f"/api/v1/qa/history/{resume_id}", headers=auth_headers)
    assert resp.json()["total"] == 3

    # 会话 A → 1 条
    resp = await client.get(
        f"/api/v1/qa/history/{resume_id}?conversation_id={conv_a}",
        headers=auth_headers,
    )
    assert resp.json()["total"] == 1

    # 会话 B → 1 条
    resp = await client.get(
        f"/api/v1/qa/history/{resume_id}?conversation_id={conv_b}",
        headers=auth_headers,
    )
    assert resp.json()["total"] == 1


@pytest.mark.asyncio
async def test_clear_history_only_current_conversation(
    client: AsyncClient, auth_headers: dict, registered_user: dict
):
    resume_id = await _insert_resume(registered_user["id"])
    conv_a = await _insert_conversation(registered_user["id"], resume_id, "A")
    conv_b = await _insert_conversation(registered_user["id"], resume_id, "B")
    await _insert_qa(registered_user["id"], resume_id, conv_a)
    await _insert_qa(registered_user["id"], resume_id, conv_b)

    # 清空会话 A
    resp = await client.delete(
        f"/api/v1/qa/history/{resume_id}?conversation_id={conv_a}",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["deleted_count"] == 1

    # 会话 A 已空，B 保留
    resp = await client.get(
        f"/api/v1/qa/history/{resume_id}?conversation_id={conv_a}",
        headers=auth_headers,
    )
    assert resp.json()["total"] == 0
    resp = await client.get(
        f"/api/v1/qa/history/{resume_id}?conversation_id={conv_b}",
        headers=auth_headers,
    )
    assert resp.json()["total"] == 1
