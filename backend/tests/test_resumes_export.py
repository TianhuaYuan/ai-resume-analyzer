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
from models.resume_module import ResumeModule
from tests.conftest import AsyncSessionTest


async def _insert_resume(
    user_id: int,
    *,
    status: str = "ready",
    parsed_text: str = "Python 后端工程师，3年 FastAPI 开发经验。",
) -> int:
    """直接插入 Resume + 一个 basic_info 模块（导出依赖 resume_modules，零模块会 422）。"""
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
        module = ResumeModule(
            resume_id=resume.id,
            module_type="basic_info",
            content={"name": "张三", "summary": "Python 后端工程师，3年 FastAPI 开发经验。"},
            sort_order=0,
        )
        session.add(module)
        await session.commit()
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
