"""C3: 数据导出 API 测试。

验证：
- 导出包含账户/简历/问答历史
- 敏感字段（password_hash）不泄露
- 未登录 → 401
- 只导出当前用户数据（不含他人）
"""

import pytest
from httpx import AsyncClient

from tests.conftest import AsyncSessionTest


async def _seed_user_data(user_id: int) -> None:
    """为用户直插简历 + 问答历史。"""
    from models.qa_history import QAHistory
    from models.resume import Resume
    from models.resume_module import ResumeModule

    async with AsyncSessionTest() as session:
        resume = Resume(
            user_id=user_id,
            filename="export.pdf",
            file_path="/tmp/export.pdf",
            parsed_text="张三\nPython 工程师",
            status="ready",
        )
        session.add(resume)
        await session.commit()
        await session.refresh(resume)

        session.add(
            ResumeModule(
                resume_id=resume.id,
                module_type="basic_info",
                content={"name": "张三"},
                sort_order=0,
            )
        )
        session.add(
            QAHistory(
                user_id=user_id,
                resume_id=resume.id,
                question="你的职业是什么？",
                answer="Python 工程师",
            )
        )
        await session.commit()


@pytest.mark.asyncio
async def test_export_data_requires_auth(client: AsyncClient):
    """未登录 → 401。"""
    resp = await client.get("/api/v1/auth/export-data")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_export_data_contains_user_data(
    client: AsyncClient, auth_headers: dict, registered_user: dict
):
    """导出包含账户/简历/模块/问答历史，且不泄露 password_hash。"""
    await _seed_user_data(registered_user["id"])

    resp = await client.get("/api/v1/auth/export-data", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()

    assert data["account"]["username"] == registered_user["username"]
    assert "password_hash" not in json_dumps(data), "不得导出密码哈希"
    assert "password" not in json_dumps(data).lower()

    assert len(data["resumes"]) == 1
    assert data["resumes"][0]["filename"] == "export.pdf"
    assert data["resumes"][0]["modules"][0]["module_type"] == "basic_info"

    assert len(data["qa_history"]) == 1
    assert data["qa_history"][0]["question"] == "你的职业是什么？"
    assert data["exported_at"]


@pytest.mark.asyncio
async def test_export_data_isolated_between_users(
    client: AsyncClient, auth_headers: dict, registered_user: dict
):
    """A 的导出不包含 B 的数据。"""
    from tests.test_isolation import _register_second_user

    await _seed_user_data(registered_user["id"])

    other = await _register_second_user(client)
    resp = await client.get("/api/v1/auth/export-data", headers=other)
    assert resp.status_code == 200
    data = resp.json()

    assert data["resumes"] == [], "B 的导出不应包含 A 的简历"
    assert data["qa_history"] == []


def json_dumps(obj) -> str:
    import json

    return json.dumps(obj, ensure_ascii=False)
