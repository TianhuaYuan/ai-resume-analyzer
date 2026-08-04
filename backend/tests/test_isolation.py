"""C4: 越权隔离测试套件（跨用户资源访问隔离）。

验证用户 A 的资源（简历/问答历史/编辑锁），用户 B 的任何操作必须 404：
- 简历：详情/更新/删除/重试/导出/预览/后台分析/编辑锁
- 问答：提问/历史
覆盖所有带 user_id 隔离的读写端点，防止越权漏洞回归。
"""

import pytest
from httpx import AsyncClient

from tests.conftest import AsyncSessionTest


async def _register_second_user(client: AsyncClient) -> dict:
    """注册第二个用户（走邮箱验证码流程）并登录，返回其 auth headers。"""
    import uuid as _uuid

    suffix = _uuid.uuid4().hex[:8]
    user_data = {
        "username": f"b_{suffix}",
        "email": f"b_{suffix}@ex.com",
        "password": "Test1234!",
        "password_confirm": "Test1234!",
    }

    # 邮箱验证码（与 conftest.registered_user 相同的测试姿势）
    await client.post("/api/v1/auth/send-code", json={"email": user_data["email"]})
    from services.verification_service import _CODE_KEY_PREFIX, _in_memory_codes

    code_key = f"{_CODE_KEY_PREFIX}{user_data['email']}"
    code_entry = _in_memory_codes.get(code_key)
    verification_code = code_entry["code"] if code_entry else "123456"

    resp = await client.post(
        "/api/v1/auth/register",
        json={**user_data, "verification_code": verification_code},
    )
    assert resp.status_code == 201, resp.text

    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": user_data["email"], "password": user_data["password"]},
    )
    assert resp.status_code == 200, resp.text
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


async def _insert_resume(owner_id: int, *, status: str = "ready") -> int:
    """为 owner_id 直插一份简历，返回 id。"""
    from models.resume import Resume

    async with AsyncSessionTest() as session:
        resume = Resume(
            user_id=owner_id,
            filename="victim.pdf",
            file_path="/tmp/victim.pdf",
            parsed_text="张三\nPython 工程师",
            status=status,
        )
        session.add(resume)
        await session.commit()
        await session.refresh(resume)
        return resume.id


@pytest.mark.asyncio
async def test_other_user_get_resume_404(client: AsyncClient, auth_headers, registered_user):
    """B 查看 A 的简历详情 → 404。"""
    resume_id = await _insert_resume(registered_user["id"])
    other = await _register_second_user(client)

    resp = await client.get(f"/api/v1/resumes/{resume_id}", headers=other)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_other_user_update_resume_404(client: AsyncClient, auth_headers, registered_user):
    """B 编辑 A 的简历（draft 模式）→ 404。"""
    resume_id = await _insert_resume(registered_user["id"])
    other = await _register_second_user(client)

    resp = await client.put(
        f"/api/v1/resumes/{resume_id}?mode=draft",
        json={"filename": "hack.pdf", "modules": [], "style": {}},
        headers=other,
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_other_user_delete_resume_404(client: AsyncClient, auth_headers, registered_user):
    """B 删除 A 的简历 → 404（非 204）。"""
    resume_id = await _insert_resume(registered_user["id"])
    other = await _register_second_user(client)

    resp = await client.delete(f"/api/v1/resumes/{resume_id}", headers=other)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_other_user_retry_resume_404(client: AsyncClient, auth_headers, registered_user):
    """B 重试 A 的失败简历 → 404。"""
    resume_id = await _insert_resume(registered_user["id"], status="failed")
    other = await _register_second_user(client)

    resp = await client.post(f"/api/v1/resumes/{resume_id}/retry", headers=other)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_other_user_export_resume_404(client: AsyncClient, auth_headers, registered_user):
    """B 导出 A 的简历 → 404。"""
    resume_id = await _insert_resume(registered_user["id"])
    other = await _register_second_user(client)

    resp = await client.get(f"/api/v1/resumes/{resume_id}/export", headers=other)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_other_user_preview_resume_404(client: AsyncClient, auth_headers, registered_user):
    """B 预览 A 的简历 → 404。"""
    resume_id = await _insert_resume(registered_user["id"])
    other = await _register_second_user(client)

    resp = await client.get(f"/api/v1/resumes/{resume_id}/preview", headers=other)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_other_user_analyze_background_404(client: AsyncClient, auth_headers, registered_user):
    """B 触发 A 的简历后台分析 → 404。"""
    resume_id = await _insert_resume(registered_user["id"])
    other = await _register_second_user(client)

    resp = await client.post(f"/api/v1/resumes/{resume_id}/analyze-background", headers=other)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_other_user_edit_lock_404(client: AsyncClient, auth_headers, registered_user):
    """B 获取 A 的简历编辑锁 → 404。"""
    resume_id = await _insert_resume(registered_user["id"])
    other = await _register_second_user(client)

    resp = await client.post(f"/api/v1/resumes/{resume_id}/lock", headers=other)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_other_user_ask_404(client: AsyncClient, auth_headers, registered_user, monkeypatch):
    """B 对 A 的简历提问 → 404（不触达 RAG）。"""
    resume_id = await _insert_resume(registered_user["id"])
    other = await _register_second_user(client)

    async def _fake_graph(resume_id, question):
        raise AssertionError("不应触达 RAG 图")

    monkeypatch.setattr("api.qa._run_agentic_rag", _fake_graph)

    resp = await client.post(
        "/api/v1/qa/ask",
        json={"resume_id": resume_id, "question": "这个人的职业是什么？"},
        headers=other,
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_other_user_qa_history_404(client: AsyncClient, auth_headers, registered_user):
    """B 查 A 的问答历史 → 404。"""
    resume_id = await _insert_resume(registered_user["id"])
    other = await _register_second_user(client)

    resp = await client.get(f"/api/v1/qa/history/{resume_id}", headers=other)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_other_user_match_jd_404(client: AsyncClient, auth_headers, registered_user):
    """B 对 A 的简历做 JD 匹配 → 404。"""
    resume_id = await _insert_resume(registered_user["id"])
    other = await _register_second_user(client)

    resp = await client.post(
        f"/api/v1/resumes/{resume_id}/match-jd",
        json={"jd_text": "需要 Python 工程师"},
        headers=other,
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_owner_still_has_access(client: AsyncClient, auth_headers, registered_user):
    """对照：A 本人对 A 的简历访问不受影响（防过度收紧）。"""
    resume_id = await _insert_resume(registered_user["id"])

    resp = await client.get(f"/api/v1/resumes/{resume_id}", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["id"] == resume_id
