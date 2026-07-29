"""QA 历史管理测试：删除（清空 + 单条）+ 关键词搜索。

覆盖：
- DELETE /api/v1/qa/history/{resume_id}  清空该简历的所有问答
- DELETE /api/v1/qa/{qa_id}               删单条问答
- GET  /api/v1/qa/history/{resume_id}?keyword=xxx  关键词搜索

TDD 红：端点尚未实现，应返回 405 Method Not Allowed 或 422/404。
TDD 绿：实现端点后所有用例通过。
"""

import pytest
from httpx import AsyncClient

from models.qa_history import QAHistory
from models.resume import Resume
from tests.conftest import AsyncSessionTest


async def _get_verification_code(client: AsyncClient, email: str) -> str:
    """调用 send-code 并返回验证码（从内存中读取）。"""
    await client.post("/api/v1/auth/send-code", json={"email": email})
    from services.verification_service import _in_memory_codes, _CODE_KEY_PREFIX
    key = f"{_CODE_KEY_PREFIX}{email}"
    entry = _in_memory_codes.get(key)
    return entry["code"] if entry else "123456"


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


async def _insert_qa(
    user_id: int,
    resume_id: int,
    *,
    question: str = "Python 是什么？",
    answer: str = "Python 是一门解释型编程语言。",
    sources: list | None = None,
) -> int:
    async with AsyncSessionTest() as session:
        qa = QAHistory(
            user_id=user_id,
            resume_id=resume_id,
            question=question,
            answer=answer,
            sources=sources or [],
        )
        session.add(qa)
        await session.commit()
        await session.refresh(qa)
        return qa.id


# ── DELETE history ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_delete_history_without_auth(client: AsyncClient):
    """未登录 → 401。"""
    resp = await client.delete("/api/v1/qa/history/1")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_delete_history_nonexistent_resume(client: AsyncClient, auth_headers: dict):
    """清空不存在的 resume → 404（归属校验先于删除）。"""
    resp = await client.delete("/api/v1/qa/history/99999", headers=auth_headers)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_history_success(
    client: AsyncClient, auth_headers: dict, registered_user: dict
):
    """成功清空 → 200 + deleted_count。"""
    user_id = registered_user["id"]
    resume_id = await _insert_resume(user_id)
    await _insert_qa(user_id, resume_id, question="Q1", answer="A1")
    await _insert_qa(user_id, resume_id, question="Q2", answer="A2")
    await _insert_qa(user_id, resume_id, question="Q3", answer="A3")

    resp = await client.delete(f"/api/v1/qa/history/{resume_id}", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["deleted_count"] == 3

    # 再查历史应该是空
    resp2 = await client.get(f"/api/v1/qa/history/{resume_id}", headers=auth_headers)
    assert resp2.json()["total"] == 0


@pytest.mark.asyncio
async def test_delete_history_cross_user_404(
    client: AsyncClient, auth_headers: dict, registered_user: dict
):
    """越权：用户 A 的 token 清用户 B 的简历历史 → 404（归属校验拦截）。"""
    # 用户 A 准备
    user_a_id = registered_user["id"]
    resume_a = await _insert_resume(user_a_id)
    await _insert_qa(user_a_id, resume_a, question="A1", answer="A1 ans")

    # 注册用户 B（需要先获取验证码）
    code_b = await _get_verification_code(client, "userb@test.com")
    resp_b = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "userb@test.com",
            "password": "Pass1234!",
            "password_confirm": "Pass1234!",
            "username": "userb",
            "verification_code": code_b,
        },
    )
    assert resp_b.status_code == 201
    login_b = await client.post(
        "/api/v1/auth/login",
        json={"email": "userb@test.com", "password": "Pass1234!"},
    )
    headers_b = {"Authorization": f"Bearer {login_b.json()['access_token']}"}

    # 用户 B 尝试清用户 A 的简历历史（resume_id 属于 A）
    resp = await client.delete(f"/api/v1/qa/history/{resume_a}", headers=headers_b)
    assert resp.status_code == 404


# ── DELETE single qa ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_delete_qa_without_auth(client: AsyncClient):
    """未登录 → 401。"""
    resp = await client.delete("/api/v1/qa/1")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_delete_qa_nonexistent(client: AsyncClient, auth_headers: dict):
    """删不存在的 qa_id → 404。"""
    resp = await client.delete("/api/v1/qa/99999", headers=auth_headers)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_qa_success(client: AsyncClient, auth_headers: dict, registered_user: dict):
    """成功删单条 → 204。"""
    user_id = registered_user["id"]
    resume_id = await _insert_resume(user_id)
    qa_id = await _insert_qa(user_id, resume_id, question="Q1", answer="A1")

    resp = await client.delete(f"/api/v1/qa/{qa_id}", headers=auth_headers)
    assert resp.status_code == 204

    # 再查历史，total 应该是 0
    resp2 = await client.get(f"/api/v1/qa/history/{resume_id}", headers=auth_headers)
    assert resp2.json()["total"] == 0


@pytest.mark.asyncio
async def test_delete_qa_cross_user_404(
    client: AsyncClient, auth_headers: dict, registered_user: dict
):
    """越权：用户 B 删用户 A 的 qa → 404。"""
    user_a_id = registered_user["id"]
    resume_a = await _insert_resume(user_a_id)
    qa_a_id = await _insert_qa(user_a_id, resume_a, question="A1", answer="A1 ans")

    # 注册 B
    code_b = await _get_verification_code(client, "userb2@test.com")
    resp_b = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "userb2@test.com",
            "password": "Pass1234!",
            "password_confirm": "Pass1234!",
            "username": "userb2",
            "verification_code": code_b,
        },
    )
    assert resp_b.status_code == 201
    login_b = await client.post(
        "/api/v1/auth/login",
        json={"email": "userb2@test.com", "password": "Pass1234!"},
    )
    headers_b = {"Authorization": f"Bearer {login_b.json()['access_token']}"}

    # B 删 A 的 qa
    resp = await client.delete(f"/api/v1/qa/{qa_a_id}", headers=headers_b)
    assert resp.status_code == 404


# ── GET history keyword 搜索 ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_history_keyword_filter(
    client: AsyncClient, auth_headers: dict, registered_user: dict
):
    """keyword 过滤：匹配 question 或 answer。"""
    user_id = registered_user["id"]
    resume_id = await _insert_resume(user_id)
    await _insert_qa(user_id, resume_id, question="Python 是什么？", answer="编程语言")
    await _insert_qa(user_id, resume_id, question="Java 是什么？", answer="另一门编程语言")
    await _insert_qa(user_id, resume_id, question="FastAPI 怎么用？", answer="Python Web 框架")

    # 搜 Python：应匹配 Q1（question 含 Python）和 Q3（answer 含 Python）
    resp = await client.get(
        f"/api/v1/qa/history/{resume_id}?keyword=Python",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 2
    questions = [item["question"] for item in data["items"]]
    assert "Python 是什么？" in questions
    assert "FastAPI 怎么用？" in questions
    assert "Java 是什么？" not in questions


@pytest.mark.asyncio
async def test_history_keyword_empty_returns_all(
    client: AsyncClient, auth_headers: dict, registered_user: dict
):
    """keyword 空字符串 → 不过滤，返回全部。"""
    user_id = registered_user["id"]
    resume_id = await _insert_resume(user_id)
    await _insert_qa(user_id, resume_id, question="Q1", answer="A1")
    await _insert_qa(user_id, resume_id, question="Q2", answer="A2")

    resp = await client.get(
        f"/api/v1/qa/history/{resume_id}?keyword=",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["total"] == 2


@pytest.mark.asyncio
async def test_history_keyword_no_match(
    client: AsyncClient, auth_headers: dict, registered_user: dict
):
    """keyword 无匹配 → 200 + total=0。"""
    user_id = registered_user["id"]
    resume_id = await _insert_resume(user_id)
    await _insert_qa(user_id, resume_id, question="Python 是什么？", answer="编程语言")

    resp = await client.get(
        f"/api/v1/qa/history/{resume_id}?keyword=JavaScript",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["total"] == 0
