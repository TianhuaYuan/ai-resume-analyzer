"""
简历模块测试：认证校验 / 列表 / 详情。
上传和删除涉及文件系统和 ChromaDB，放在集成测试中验证。
"""
import pytest
from httpx import AsyncClient


# ── 认证校验 ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_resumes_without_auth(client: AsyncClient):
    """未登录访问简历列表 → 401。"""
    resp = await client.get("/api/resumes")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_get_resume_without_auth(client: AsyncClient):
    """未登录访问简历详情 → 401。"""
    resp = await client.get("/api/resumes/1")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_upload_without_auth(client: AsyncClient):
    """未登录上传简历 → 401。"""
    resp = await client.post("/api/resumes", files={"file": ("test.pdf", b"fake", "application/pdf")})
    assert resp.status_code == 401


# ── 列表 ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_resumes_empty(client: AsyncClient, auth_headers: dict):
    """新用户简历列表为空。"""
    resp = await client.get("/api/resumes", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["items"] == []
    assert data["total"] == 0


# ── 详情 ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_nonexistent_resume(client: AsyncClient, auth_headers: dict):
    """访问不存在的简历 → 404。"""
    resp = await client.get("/api/resumes/99999", headers=auth_headers)
    assert resp.status_code == 404


# ── 删除 ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_delete_nonexistent_resume(client: AsyncClient, auth_headers: dict):
    """删除不存在的简历 → 404。"""
    resp = await client.delete("/api/resumes/99999", headers=auth_headers)
    assert resp.status_code == 404
