"""
简历模块测试：认证校验 / 列表 / 详情。
上传和删除涉及文件系统和 ChromaDB，放在集成测试中验证。
"""

import pytest
from httpx import AsyncClient

from models.resume import Resume
from tests.conftest import AsyncSessionTest


async def _insert_resume(
    user_id: int,
    *,
    parsed_text: str = "Python 后端工程师，3年 FastAPI 开发经验。",
    status: str = "ready",
) -> int:
    """直接插入 Resume 记录，返回 id。"""
    async with AsyncSessionTest() as session:
        resume = Resume(
            user_id=user_id,
            filename="test.pdf",
            file_path="/tmp/test.pdf",
            parsed_text=parsed_text,
            status=status,
        )
        session.add(resume)
        await session.commit()
        await session.refresh(resume)
        return resume.id


# ── 认证校验 ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_resumes_without_auth(client: AsyncClient):
    """未登录访问简历列表 → 401。"""
    resp = await client.get("/api/v1/resumes")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_get_resume_without_auth(client: AsyncClient):
    """未登录访问简历详情 → 401。"""
    resp = await client.get("/api/v1/resumes/1")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_upload_without_auth(client: AsyncClient):
    """未登录上传简历 → 401。"""
    resp = await client.post(
        "/api/v1/resumes", files={"file": ("test.pdf", b"fake", "application/pdf")}
    )
    assert resp.status_code == 401


# ── 列表 ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_resumes_empty(client: AsyncClient, auth_headers: dict):
    """新用户简历列表为空。"""
    resp = await client.get("/api/v1/resumes", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["items"] == []
    assert data["total"] == 0


# ── P1-16: 分页参数校验 ──────────────────────────────


@pytest.mark.asyncio
async def test_list_resumes_limit_too_small(client: AsyncClient, auth_headers: dict):
    """limit=0 → 422（最小值 1）。"""
    resp = await client.get("/api/v1/resumes?limit=0", headers=auth_headers)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_list_resumes_limit_too_large(client: AsyncClient, auth_headers: dict):
    """limit=101 → 422（最大值 100）。"""
    resp = await client.get("/api/v1/resumes?limit=101", headers=auth_headers)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_list_resumes_limit_boundary_ok(client: AsyncClient, auth_headers: dict):
    """limit=1 和 limit=100 边界值 → 200。"""
    for limit in (1, 100):
        resp = await client.get(f"/api/v1/resumes?limit={limit}", headers=auth_headers)
        assert resp.status_code == 200, f"limit={limit} 应通过"


@pytest.mark.asyncio
async def test_list_resumes_offset_negative(client: AsyncClient, auth_headers: dict):
    """offset=-1 → 422（最小值 0）。"""
    resp = await client.get("/api/v1/resumes?offset=-1", headers=auth_headers)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_list_resumes_offset_zero_ok(client: AsyncClient, auth_headers: dict):
    """offset=0 → 200（边界值）。"""
    resp = await client.get("/api/v1/resumes?offset=0", headers=auth_headers)
    assert resp.status_code == 200


# ── 详情 ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_nonexistent_resume(client: AsyncClient, auth_headers: dict):
    """访问不存在的简历 → 404。"""
    resp = await client.get("/api/v1/resumes/99999", headers=auth_headers)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_resume_returns_parsed_text(
    client: AsyncClient, auth_headers: dict, registered_user: dict
):
    """GET /api/v1/resumes/{id} 应返回 parsed_text 字段，供前端预览原文。"""
    text = "张三\nPython后端工程师\n3年FastAPI开发经验\n熟悉Docker和CI/CD"
    resume_id = await _insert_resume(registered_user["id"], parsed_text=text)
    resp = await client.get(f"/api/v1/resumes/{resume_id}", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "parsed_text" in data
    assert data["parsed_text"] == text


@pytest.mark.asyncio
async def test_get_resume_returns_empty_parsed_text(
    client: AsyncClient, auth_headers: dict, registered_user: dict
):
    """processing 状态的简历 parsed_text 为空字符串，也应正常返回。"""
    resume_id = await _insert_resume(
        registered_user["id"], parsed_text="", status="processing"
    )
    resp = await client.get(f"/api/v1/resumes/{resume_id}", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["parsed_text"] == ""


# ── 删除 ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_delete_nonexistent_resume(client: AsyncClient, auth_headers: dict):
    """删除不存在的简历 → 404。"""
    resp = await client.delete("/api/v1/resumes/99999", headers=auth_headers)
    assert resp.status_code == 404
