"""内联 AI 端点测试：ai/optimize、ai/check、ai/rewrite。

覆盖：
- 字段隔离指令注入（optimize/rewrite 的 system_prompt 含「只对提供的文本操作」）
- check 返回 JSON 解析 / 非 JSON 降级
- 认证与短文本校验
"""

from unittest.mock import patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from models.resume import Resume


async def _insert_resume(db: AsyncSession, user_id: int, parsed_text: str = "测试简历文本") -> int:
    resume = Resume(
        user_id=user_id,
        filename="ai.docx",
        file_path="/tmp/ai.docx",
        parsed_text=parsed_text,
    )
    db.add(resume)
    await db.commit()
    await db.refresh(resume)
    return resume.id


@pytest.fixture
async def _resume(registered_user: dict, db_session: AsyncSession) -> int:
    return await _insert_resume(db_session, registered_user["id"])


@pytest.mark.asyncio
async def test_optimize_requires_auth(client: AsyncClient):
    resp = await client.post(
        "/api/v1/resumes/1/ai/optimize",
        json={"text": "负责前端开发，提升性能", "module_type": "work_experience"},
    )
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_optimize_rejects_short_text(client: AsyncClient, auth_headers: dict, _resume: int):
    resp = await client.post(
        f"/api/v1/resumes/{_resume}/ai/optimize",
        json={"text": "短", "module_type": "basic_info"},
        headers=auth_headers,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_optimize_prompt_includes_field_isolation(
    client: AsyncClient, auth_headers: dict, _resume: int
):
    """优化 prompt 必须带字段隔离指令：不改写姓名等其他字段。"""
    captured = {}

    async def fake_llm_generate(system: str, user: str, **kwargs):
        captured["system"] = system
        captured["user"] = user
        return "深耕前端性能优化，主导组件库建设"

    with patch("services.rag.pipeline.llm_generate", new=fake_llm_generate):
        resp = await client.post(
            f"/api/v1/resumes/{_resume}/ai/optimize",
            json={"text": "负责前端开发，提升性能", "module_type": "work_experience"},
            headers=auth_headers,
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["optimized_text"] == "深耕前端性能优化，主导组件库建设"
    # 隔离指令：明确「不得修改姓名/联系方式等字段外信息」
    assert "只对用户提供的这段文本进行操作" in captured["system"]
    assert "姓名" in captured["system"] and "虚构" in captured["system"]


@pytest.mark.asyncio
async def test_rewrite_prompt_includes_field_isolation(
    client: AsyncClient, auth_headers: dict, _resume: int
):
    """改写 prompt 必须带字段隔离指令 + 改写指令透传。"""
    captured = {}

    async def fake_llm_generate(system: str, user: str, **kwargs):
        captured["system"] = system
        captured["user"] = user
        return "更简洁的版本"

    with patch("services.rag.pipeline.llm_generate", new=fake_llm_generate):
        resp = await client.post(
            f"/api/v1/resumes/{_resume}/ai/rewrite",
            json={
                "text": "负责前端开发，提升性能",
                "instruction": "更简洁专业",
                "module_type": "work_experience",
            },
            headers=auth_headers,
        )

    assert resp.status_code == 200
    assert resp.json()["rewritten_text"] == "更简洁的版本"
    assert "只对用户提供的这段文本进行操作" in captured["system"]
    assert "更简洁专业" in captured["user"]


@pytest.mark.asyncio
async def test_check_parses_json(client: AsyncClient, auth_headers: dict, _resume: int):
    """check 返回合法 JSON → 解析为 issues 列表。"""
    async def fake_llm_generate(system: str, user: str, **kwargs):
        return '{"issues": [{"severity": "high", "category": "量化问题", "description": "缺少数据", "field": "工作描述"}]}'

    with patch("services.rag.pipeline.llm_generate", new=fake_llm_generate):
        resp = await client.post(
            f"/api/v1/resumes/{_resume}/ai/check",
            json={"text": "负责前端开发", "module_type": "work_experience", "check_field": "工作描述"},
            headers=auth_headers,
        )

    assert resp.status_code == 200
    issues = resp.json()["issues"]
    assert len(issues) == 1
    assert issues[0]["severity"] == "high"
    assert issues[0]["field"] == "工作描述"


@pytest.mark.asyncio
async def test_check_falls_back_on_invalid_json(
    client: AsyncClient, auth_headers: dict, _resume: int
):
    """check 返回非 JSON → 降级为单个 medium issue。"""
    async def fake_llm_generate(system: str, user: str, **kwargs):
        return "这不是 JSON"

    with patch("services.rag.pipeline.llm_generate", new=fake_llm_generate):
        resp = await client.post(
            f"/api/v1/resumes/{_resume}/ai/check",
            json={"text": "负责前端开发", "module_type": "work_experience"},
            headers=auth_headers,
        )

    assert resp.status_code == 200
    issues = resp.json()["issues"]
    assert len(issues) == 1
    assert issues[0]["severity"] == "medium"
