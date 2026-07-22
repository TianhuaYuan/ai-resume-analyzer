"""GET /api/v1/resumes/{id}/export 端点测试。

P1.2 导出报告功能：
- format=markdown: 返回 Markdown 格式综合报告
- 401 未登录
- 404 简历不存在
- 409 简历未就绪

覆盖：
- 200 成功导出 Markdown
- 401/404/409 错误场景
"""

from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from models.resume import Resume
from tests.conftest import AsyncSessionTest


async def _insert_resume(
    user_id: int,
    *,
    status: str = "ready",
    parsed_text: str = "Python 后端工程师，3年 FastAPI 开发经验。",
) -> int:
    async with AsyncSessionTest() as session:
        resume = Resume(
            user_id=user_id,
            filename="张三_后端.pdf",
            file_path="/tmp/test.pdf",
            parsed_text=parsed_text,
            status=status,
        )
        session.add(resume)
        await session.commit()
        await session.refresh(resume)
        return resume.id


@pytest.mark.asyncio
async def test_export_without_auth(client: AsyncClient):
    """未登录导出 → 401。"""
    resp = await client.get("/api/v1/resumes/1/export?format=markdown")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_export_nonexistent_resume(client: AsyncClient, auth_headers: dict):
    """导出不存在的简历 → 404。"""
    resp = await client.get(
        "/api/v1/resumes/99999/export?format=markdown",
        headers=auth_headers,
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_export_processing_resume_returns_409(
    client: AsyncClient, auth_headers: dict, registered_user: dict
):
    """processing 状态简历 → 409。"""
    resume_id = await _insert_resume(registered_user["id"], status="processing", parsed_text="")
    resp = await client.get(
        f"/api/v1/resumes/{resume_id}/export?format=markdown",
        headers=auth_headers,
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_export_markdown_success(
    client: AsyncClient, auth_headers: dict, registered_user: dict
):
    """成功导出 Markdown → 200 + markdown 内容。"""
    resume_id = await _insert_resume(registered_user["id"])
    resp = await client.get(
        f"/api/v1/resumes/{resume_id}/export?format=markdown",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    # 返回 Markdown 内容
    assert "text/markdown" in resp.headers.get("content-type", "")
    # 内容包含简历原文
    body = resp.text
    assert "Python" in body
    # 内容包含报告标题
    assert "简历分析报告" in body or "# " in body


@pytest.mark.asyncio
async def test_export_markdown_contains_filename(
    client: AsyncClient, auth_headers: dict, registered_user: dict
):
    """导出的 Markdown 应包含文件名。"""
    resume_id = await _insert_resume(registered_user["id"])
    resp = await client.get(
        f"/api/v1/resumes/{resume_id}/export?format=markdown",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    body = resp.text
    assert "张三_后端.pdf" in body
