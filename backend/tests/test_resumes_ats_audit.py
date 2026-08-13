"""
ATS 审计 API 测试（P0-A）。

覆盖：401 / 404 / 409 / 422 + 问题检测 + PDF 路径 mock。
"""

import pytest
from httpx import AsyncClient
from unittest.mock import patch

from models.resume import Resume
from models.resume_module import ResumeModule
from tests.conftest import AsyncSessionTest


async def _insert_resume_with_modules(
    user_id: int,
    *,
    status: str = "ready",
    module_type: str = "basic_info",
    content: dict | None = None,
) -> int:
    """直接插入 Resume + ResumeModule 记录，返回 resume_id。"""
    async with AsyncSessionTest() as session:
        resume = Resume(
            user_id=user_id,
            filename="test.pdf",
            file_path="/tmp/test.pdf",
            parsed_text="Python 后端工程师，3年 FastAPI 开发经验。",
            status=status,
        )
        session.add(resume)
        await session.flush()

        module = ResumeModule(
            resume_id=resume.id,
            module_type=module_type,
            content=content or {"name": "张三", "summary": "资深后端工程师"},
            sort_order=0,
        )
        session.add(module)
        await session.commit()
        return resume.id


async def _insert_resume_draft_with_modules(
    user_id: int,
) -> int:
    """插入 draft 状态的简历 + 模块。"""
    return await _insert_resume_with_modules(user_id, status="draft")


# ── 认证校验 ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_ats_audit_without_auth(client: AsyncClient):
    """未登录执行 ATS 审计 → 401。"""
    resp = await client.post("/api/v1/resumes/1/ats-audit")
    assert resp.status_code == 401


# ── 404 校验 ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_ats_audit_resume_not_found(client: AsyncClient, auth_headers: dict):
    """审计不存在的简历 → 404。"""
    resp = await client.post("/api/v1/resumes/99999/ats-audit", headers=auth_headers)
    assert resp.status_code == 404


# ── 409 校验（状态未就绪） ──────────────────────────────


@pytest.mark.asyncio
async def test_ats_audit_resume_not_ready(client: AsyncClient, auth_headers: dict):
    """审计未就绪的简历 → 409。"""
    async with AsyncSessionTest() as session:
        # 获取当前测试用户 ID
        from sqlalchemy import select
        from models.user import User
        result = await session.execute(select(User).limit(1))
        user = result.scalar_one_or_none()
        if user is None:
            pytest.skip("No test user found")

    resume_id = await _insert_resume_with_modules(user.id, status="processing")
    resp = await client.post(
        f"/api/v1/resumes/{resume_id}/ats-audit", headers=auth_headers
    )
    assert resp.status_code == 409


# ── 422 校验（零模块） ──────────────────────────────────


@pytest.mark.asyncio
async def test_ats_audit_no_modules(client: AsyncClient, auth_headers: dict):
    """审计零模块简历 → 422。"""
    async with AsyncSessionTest() as session:
        from sqlalchemy import select
        from models.user import User
        result = await session.execute(select(User).limit(1))
        user = result.scalar_one_or_none()
        if user is None:
            pytest.skip("No test user found")

    # 插入无模块的简历
    async with AsyncSessionTest() as session:
        resume = Resume(
            user_id=user.id,
            filename="empty.pdf",
            file_path="/tmp/empty.pdf",
            parsed_text="",
            status="ready",
        )
        session.add(resume)
        await session.commit()
        await session.refresh(resume)
        resume_id = resume.id

    resp = await client.post(
        f"/api/v1/resumes/{resume_id}/ats-audit", headers=auth_headers
    )
    assert resp.status_code == 422


# ── 成功路径（HTML 路径） ───────────────────────────────


@pytest.mark.asyncio
async def test_ats_audit_success_html(client: AsyncClient, auth_headers: dict):
    """正常简历 ATS 审计 → 200 + 结构化结果。"""
    async with AsyncSessionTest() as session:
        from sqlalchemy import select
        from models.user import User
        result = await session.execute(select(User).limit(1))
        user = result.scalar_one_or_none()
        if user is None:
            pytest.skip("No test user found")

    resume_id = await _insert_resume_with_modules(
        user.id,
        content={"name": "张三", "summary": "资深后端工程师，精通 Python 和 FastAPI"},
    )

    resp = await client.post(
        f"/api/v1/resumes/{resume_id}/ats-audit", headers=auth_headers
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["resume_id"] == resume_id
    assert isinstance(data["ats_score"], int)
    assert 0 <= data["ats_score"] <= 100
    assert isinstance(data["issues"], list)
    assert data["method"] in ("html", "pdf", "pdf+html")
    assert isinstance(data["pdf_available"], bool)
    assert isinstance(data["warnings"], list)


# ── 问题检测 ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_ats_audit_detects_special_symbols(
    client: AsyncClient, auth_headers: dict
):
    """含特殊符号的简历应被检出。"""
    async with AsyncSessionTest() as session:
        from sqlalchemy import select
        from models.user import User
        result = await session.execute(select(User).limit(1))
        user = result.scalar_one_or_none()
        if user is None:
            pytest.skip("No test user found")

    resume_id = await _insert_resume_with_modules(
        user.id,
        content={
            "name": "张三",
            "summary": "● 资深工程师 ★ 精通 Python ◆ FastAPI 专家",
        },
    )

    resp = await client.post(
        f"/api/v1/resumes/{resume_id}/ats-audit", headers=auth_headers
    )
    assert resp.status_code == 200
    data = resp.json()
    symbol_issues = [
        i for i in data["issues"] if i["issue_type"] == "special_symbol"
    ]
    assert len(symbol_issues) > 0


@pytest.mark.asyncio
async def test_ats_audit_detects_garbled_text(
    client: AsyncClient, auth_headers: dict
):
    """含乱码文本的简历应被检出。"""
    async with AsyncSessionTest() as session:
        from sqlalchemy import select
        from models.user import User
        result = await session.execute(select(User).limit(1))
        user = result.scalar_one_or_none()
        if user is None:
            pytest.skip("No test user found")

    resume_id = await _insert_resume_with_modules(
        user.id,
        content={
            "name": "张三",
            "summary": "工作经历：\x00\x01Python 开发经验",
        },
    )

    resp = await client.post(
        f"/api/v1/resumes/{resume_id}/ats-audit", headers=auth_headers
    )
    assert resp.status_code == 200
    data = resp.json()
    garbled_issues = [
        i for i in data["issues"] if i["issue_type"] == "garbled"
    ]
    assert len(garbled_issues) > 0


@pytest.mark.asyncio
async def test_ats_audit_detects_markdown_table(
    client: AsyncClient, auth_headers: dict
):
    """含 Markdown 表格的简历应被检出。"""
    async with AsyncSessionTest() as session:
        from sqlalchemy import select
        from models.user import User
        result = await session.execute(select(User).limit(1))
        user = result.scalar_one_or_none()
        if user is None:
            pytest.skip("No test user found")

    resume_id = await _insert_resume_with_modules(
        user.id,
        module_type="project_experience",
        content={
            "name": "项目一",
            "description": "| 技术 | 说明 |\n| --- | --- |\n| Python | 后端 |",
        },
    )

    # render_resume 会把 markdown 表格转成 HTML，text 提取后不含 | --- | 语法
    # 直接 mock render_resume 返回含 markdown 表格的 HTML
    with patch("services.resume_template.render_resume") as mock_render:
        mock_render.return_value = (
            '<h2 class="module-title">项目经历</h2>'
            '<div class="module-content">| 技术 | 说明 |\n| --- | --- |\n| Python | 后端 |</div>'
        )
        resp = await client.post(
            f"/api/v1/resumes/{resume_id}/ats-audit", headers=auth_headers
        )
    assert resp.status_code == 200
    data = resp.json()
    table_issues = [
        i for i in data["issues"] if i["issue_type"] == "table"
    ]
    assert len(table_issues) > 0


# ── PDF 路径 mock ──────────────────────────────────────


@pytest.mark.asyncio
async def test_ats_audit_pdf_path_unavailable(
    client: AsyncClient, auth_headers: dict
):
    """WeasyPrint 不可用时降级到 HTML 路径。"""
    async with AsyncSessionTest() as session:
        from sqlalchemy import select
        from models.user import User
        result = await session.execute(select(User).limit(1))
        user = result.scalar_one_or_none()
        if user is None:
            pytest.skip("No test user found")

    resume_id = await _insert_resume_with_modules(user.id)

    with patch("services.resume_export._get_weasyprint", return_value=None):
        resp = await client.post(
            f"/api/v1/resumes/{resume_id}/ats-audit", headers=auth_headers
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["method"] == "html"
        assert data["pdf_available"] is False
        assert any("WeasyPrint" in w for w in data["warnings"])


# ── draft 状态简历 ──────────────────────────────────────


@pytest.mark.asyncio
async def test_ats_audit_draft_status(client: AsyncClient, auth_headers: dict):
    """draft 状态的简历也可以执行 ATS 审计。"""
    async with AsyncSessionTest() as session:
        from sqlalchemy import select
        from models.user import User
        result = await session.execute(select(User).limit(1))
        user = result.scalar_one_or_none()
        if user is None:
            pytest.skip("No test user found")

    resume_id = await _insert_resume_draft_with_modules(user.id)

    resp = await client.post(
        f"/api/v1/resumes/{resume_id}/ats-audit", headers=auth_headers
    )
    assert resp.status_code == 200
