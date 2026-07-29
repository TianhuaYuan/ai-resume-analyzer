# -*- coding: utf-8 -*-
"""Task 5.2: 多简历对比分析 API 测试。"""

import pytest
from httpx import AsyncClient

from models.resume import Resume
from models.user import User
from tests.conftest import AsyncSessionTest


async def _insert_resume(
    user_id: int,
    *,
    filename: str = "test.pdf",
    parsed_text: str = "Python",
    idempotency_key: str | None = None,
) -> int:
    """直接插入 Resume 记录，返回 id。"""
    async with AsyncSessionTest() as session:
        resume = Resume(
            user_id=user_id,
            filename=filename,
            file_path=f"/tmp/{filename}",
            parsed_text=parsed_text,
            chunk_count=1,
            status="completed",
            idempotency_key=idempotency_key or f"test-{user_id}-{filename}",
        )
        session.add(resume)
        await session.commit()
        await session.refresh(resume)
        return resume.id


@pytest.mark.asyncio
async def test_compare_requires_resume_ids(client: AsyncClient, auth_headers: dict):
    """必须提供 resume_ids。"""
    resp = await client.post(
        "/api/v1/resumes/compare",
        json={"dimensions": ["skills"]},
        headers=auth_headers,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_compare_requires_at_least_two_resumes(client: AsyncClient, auth_headers: dict):
    """至少需要 2 份简历。"""
    resp = await client.post(
        "/api/v1/resumes/compare",
        json={"resume_ids": [1], "dimensions": ["skills"]},
        headers=auth_headers,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_compare_limits_to_five_resumes(client: AsyncClient, auth_headers: dict):
    """最多 5 份简历。"""
    resp = await client.post(
        "/api/v1/resumes/compare",
        json={"resume_ids": [1, 2, 3, 4, 5, 6], "dimensions": ["skills"]},
        headers=auth_headers,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_compare_requires_dimensions(client: AsyncClient, auth_headers: dict):
    """必须提供 dimensions。"""
    resp = await client.post(
        "/api/v1/resumes/compare",
        json={"resume_ids": [1, 2]},
        headers=auth_headers,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_compare_validates_dimension_values(client: AsyncClient, auth_headers: dict):
    """dimensions 必须是预定义值。"""
    resp = await client.post(
        "/api/v1/resumes/compare",
        json={"resume_ids": [1, 2], "dimensions": ["invalid_dim"]},
        headers=auth_headers,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_compare_returns_comparison_result(
    client: AsyncClient,
    auth_headers: dict,
    registered_user: dict,
):
    """返回对比结果。"""
    # 先创建 2 份简历
    resume_id_1 = await _insert_resume(
        registered_user["id"],
        filename="resume_a.pdf",
        parsed_text="Python, FastAPI, React\n项目：简历分析系统",
    )
    resume_id_2 = await _insert_resume(
        registered_user["id"],
        filename="resume_b.pdf",
        parsed_text="Java, Spring Boot\n项目：电商系统",
    )

    resp = await client.post(
        "/api/v1/resumes/compare",
        json={
            "resume_ids": [resume_id_1, resume_id_2],
            "dimensions": ["skills", "projects"],
        },
        headers=auth_headers,
    )
    assert resp.status_code == 200

    data = resp.json()
    assert "resumes" in data
    assert "dimensions" in data
    assert len(data["resumes"]) == 2

    # 每份简历应有 id 和 filename
    for r in data["resumes"]:
        assert "id" in r
        assert "filename" in r

    # dimensions 应包含 skills 和 projects
    dims = data["dimensions"]
    assert "skills" in dims
    assert "projects" in dims

    # skills 维度应是 dict，key 为 resume_id
    skills_dim = dims["skills"]
    assert isinstance(skills_dim, dict)
    assert str(resume_id_1) in skills_dim
    assert isinstance(skills_dim[str(resume_id_1)], list)


@pytest.mark.asyncio
async def test_compare_only_own_resumes(client: AsyncClient, auth_headers: dict):
    """只能对比自己的简历。"""
    # 创建其他用户
    async with AsyncSessionTest() as session:
        other_user = User(
            username="other-compare", 
            email="other-compare@example.com", 
            password_hash="x"
        )
        session.add(other_user)
        await session.commit()
        await session.refresh(other_user)
        other_user_id = other_user.id

        # 创建其他用户的简历
        other_resume = Resume(
            user_id=other_user_id,
            filename="other_resume.pdf",
            file_path="/tmp/other_resume.pdf",
            parsed_text="Go, Kubernetes",
            chunk_count=1,
            status="completed",
            idempotency_key=f"other-compare-{other_user_id}",
        )
        session.add(other_resume)
        await session.commit()
        await session.refresh(other_resume)
        other_resume_id = other_resume.id

    resp = await client.post(
        "/api/v1/resumes/compare",
        json={"resume_ids": [other_resume_id, 999], "dimensions": ["skills"]},
        headers=auth_headers,
    )
    # 其他用户的简历应返回 404 或 403
    assert resp.status_code in (403, 404)


@pytest.mark.asyncio
async def test_compare_processes_not_found(client: AsyncClient, auth_headers: dict):
    """不存在的简历 ID 返回 404。"""
    resp = await client.post(
        "/api/v1/resumes/compare",
        json={"resume_ids": [99999, 99998], "dimensions": ["skills"]},
        headers=auth_headers,
    )
    assert resp.status_code == 404