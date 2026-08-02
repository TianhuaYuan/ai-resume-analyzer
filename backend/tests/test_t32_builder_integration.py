"""T32: builder API 集成测试 — 补充 T23-T28 未覆盖的端到端流程。

测试范围：
1. TestEditLockAPI: 编辑锁 HTTP 端点（获取/续期/释放/冲突/404/401）
2. TestBuilderWorkflowIntegration: 端到端 builder 工作流（创建→草稿→完成→状态验证）
3. TestModuleSchemaValidation: 模块 content 校验（15 种类型/必填字段/空列表）
4. TestPreviewExportIntegration: 预览与导出集成（零模块守卫/缓存命中/格式校验）
5. TestParseToModules: 文本反解析端点（正常/空/过短/过长）

依赖 conftest.py fixtures: client / auth_headers / registered_user / db_session
asyncio_mode = auto（无需 @pytest.mark.asyncio 装饰器）
"""

import json
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from models.resume import Resume


# ═══════════════════════════════════════════════════════════════
# Helper 函数
# ═══════════════════════════════════════════════════════════════


def _basic_info_content() -> dict:
    """返回合法的 basic_info content。"""
    return {"name": "张三", "phone": "13800138000", "email": "zhangsan@test.com"}


def _education_content() -> dict:
    """返回合法的 education content。"""
    return {
        "entries": [
            {
                "school": "广东海洋大学",
                "degree": "本科",
                "major": "软件工程",
                "start_date": "2023-09",
                "end_date": "2027-06",
            }
        ]
    }


def _skills_content() -> dict:
    """返回合法的 skills content。"""
    return {
        "categories": [
            {"name": "编程语言", "items": ["Python", "JavaScript"]},
            {"name": "框架", "items": ["FastAPI", "React"]},
        ]
    }


async def _create_builder_resume(
    client: AsyncClient, headers: dict, modules: list[dict] | None = None
) -> dict:
    """通过 API 创建 builder 简历，返回响应 JSON。"""
    body: dict = {"filename": "T32测试简历"}
    if modules is not None:
        body["modules"] = modules
    resp = await client.post("/api/v1/resumes/builder", json=body, headers=headers)
    assert resp.status_code == 201, f"创建 builder 简历失败: {resp.text}"
    return resp.json()


async def _register_second_user(
    client: AsyncClient, email: str = "user2@example.com"
) -> dict:
    """注册第二个测试用户，返回 {id, email, headers}。"""
    await client.post("/api/v1/auth/send-code", json={"email": email})

    from services.verification_service import _in_memory_codes, _CODE_KEY_PREFIX

    code_key = f"{_CODE_KEY_PREFIX}{email}"
    code_entry = _in_memory_codes.get(code_key)
    verification_code = code_entry["code"] if code_entry else "123456"

    register_data = {
        "username": "user2",
        "email": email,
        "password": "Test1234!",
        "password_confirm": "Test1234!",
        "verification_code": verification_code,
    }
    resp = await client.post("/api/v1/auth/register", json=register_data)
    assert resp.status_code == 201, f"注册第二用户失败: {resp.text}"
    user_id = resp.json()["id"]

    login_resp = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "Test1234!"},
    )
    assert login_resp.status_code == 200
    token = login_resp.json()["access_token"]
    return {
        "id": user_id,
        "email": email,
        "headers": {"Authorization": f"Bearer {token}"},
    }


def _reset_in_memory_redis() -> None:
    """清空 InMemoryRedis 全局状态，防止测试间锁残留。"""
    from core.redis_client import _in_memory

    if _in_memory is not None:
        _in_memory._data.clear()
        _in_memory._expire_at.clear()


def _all_15_modules() -> list[dict]:
    """返回全部 15 种 module_type 的合法模块列表。"""
    return [
        {"module_type": "basic_info", "content": {"name": "张三"}, "sort_order": 0},
        {"module_type": "education", "content": {"entries": [{"school": "广东海洋大学"}]}, "sort_order": 1},
        {"module_type": "work_experience", "content": {"entries": [{"company": "测试公司", "position": "开发"}]}, "sort_order": 2},
        {"module_type": "project_experience", "content": {"entries": [{"name": "测试项目"}]}, "sort_order": 3},
        {"module_type": "skills", "content": {"categories": [{"name": "编程语言", "items": ["Python"]}]}, "sort_order": 4},
        {"module_type": "language", "content": {"entries": [{"name": "英语", "proficiency": "流利"}]}, "sort_order": 5},
        {"module_type": "honors", "content": {"entries": [{"title": "一等奖", "date": "2024-05"}]}, "sort_order": 6},
        {"module_type": "certificates", "content": {"entries": [{"name": "CET-6", "issuer": "教育部"}]}, "sort_order": 7},
        {"module_type": "interests", "content": {"items": ["阅读", "编程"]}, "sort_order": 8},
        {"module_type": "club_activities", "content": {"entries": [{"name": "编程社", "role": "社长"}]}, "sort_order": 9},
        {"module_type": "publications", "content": {"entries": [{"title": "测试论文", "venue": "ICML"}]}, "sort_order": 10},
        {"module_type": "recommendation", "content": {"entries": [{"name": "李教授", "title": "教授"}]}, "sort_order": 11},
        {"module_type": "social_links", "content": {"github": "https://github.com/test"}, "sort_order": 12},
        {"module_type": "other", "content": {"content": "其他补充内容"}, "sort_order": 13},
        {"module_type": "custom", "content": {"title": "自定义模块", "content": "自定义内容"}, "sort_order": 14},
    ]


def _default_style() -> dict:
    """返回默认样式配置。"""
    return {
        "template_id": "default",
        "font_family": "Noto Sans CJK SC",
        "font_size": "14px",
        "line_height": 1.6,
        "spacing": "8px",
        "accent_color": "#2563eb",
    }


def _complete_mocks():
    """返回 complete 流程需要的 mock context manager 元组。"""
    return (
        patch("services.resume_builder.ensure_indexed", new_callable=AsyncMock),
        patch("services.resume_builder.embedding_cache.clear_resume", new_callable=AsyncMock),
        patch("services.react_agent.memory.build_l3_profile_background", new_callable=AsyncMock),
    )


# ═══════════════════════════════════════════════════════════════
# 1. 编辑锁 API 集成测试
# ═══════════════════════════════════════════════════════════════


class TestEditLockAPI:
    """POST/DELETE /resumes/{id}/lock 端点集成测试。

    锁使用 InMemoryRedis 降级（测试环境无 Redis），需在每个测试前清空全局状态。
    """

    def setup_method(self):
        _reset_in_memory_redis()

    def teardown_method(self):
        _reset_in_memory_redis()

    async def test_acquire_lock_success(
        self, client: AsyncClient, auth_headers: dict, db_session: AsyncSession,
        registered_user: dict,
    ):
        """POST /resumes/{id}/lock → 200 + lock_token。"""
        data = await _create_builder_resume(client, auth_headers)
        resume_id = data["id"]

        resp = await client.post(
            f"/api/v1/resumes/{resume_id}/lock", headers=auth_headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["locked"] is True
        assert body["lock_token"] is not None
        assert body["holder_id"] == registered_user["id"]

    async def test_acquire_lock_conflict(
        self, client: AsyncClient, auth_headers: dict, db_session: AsyncSession,
        registered_user: dict,
    ):
        """第一个用户持有锁后，第二个用户获取 → 409。

        锁以 resume_id 为 key（不区分 user），只要锁被持有且 token 属于不同 user，
        第二个 user 就会收到 409。此处通过 DB 转移归属让第二个 user 通过 ownership 检查。
        """
        # User A 创建简历并获取锁
        data = await _create_builder_resume(client, auth_headers)
        resume_id = data["id"]
        resp_a = await client.post(
            f"/api/v1/resumes/{resume_id}/lock", headers=auth_headers,
        )
        assert resp_a.status_code == 200

        # 注册第二个用户
        user_b = await _register_second_user(client)

        # 转移简历归属到 User B（使 B 通过 ownership 检查）
        await db_session.execute(
            update(Resume).where(Resume.id == resume_id).values(user_id=user_b["id"])
        )
        await db_session.commit()

        # User B 尝试获取锁 → 409（锁仍被 User A 持有）
        resp_b = await client.post(
            f"/api/v1/resumes/{resume_id}/lock", headers=user_b["headers"],
        )
        assert resp_b.status_code == 409

    async def test_acquire_lock_same_user_reacquire(
        self, client: AsyncClient, auth_headers: dict,
    ):
        """同一用户再次获取锁 → 成功（返回新 token）。"""
        data = await _create_builder_resume(client, auth_headers)
        resume_id = data["id"]

        resp1 = await client.post(
            f"/api/v1/resumes/{resume_id}/lock", headers=auth_headers,
        )
        assert resp1.status_code == 200
        token1 = resp1.json()["lock_token"]

        resp2 = await client.post(
            f"/api/v1/resumes/{resume_id}/lock", headers=auth_headers,
        )
        assert resp2.status_code == 200
        token2 = resp2.json()["lock_token"]
        assert token2 != token1  # 新 token

    async def test_heartbeat_renew_success(
        self, client: AsyncClient, auth_headers: dict,
    ):
        """POST /resumes/{id}/lock/heartbeat 正确 token → 200。"""
        data = await _create_builder_resume(client, auth_headers)
        resume_id = data["id"]

        acquire_resp = await client.post(
            f"/api/v1/resumes/{resume_id}/lock", headers=auth_headers,
        )
        token = acquire_resp.json()["lock_token"]

        resp = await client.post(
            f"/api/v1/resumes/{resume_id}/lock/heartbeat",
            json={"lock_token": token},
            headers=auth_headers,
        )
        assert resp.status_code == 200

    async def test_heartbeat_wrong_token(
        self, client: AsyncClient, auth_headers: dict,
    ):
        """POST /resumes/{id}/lock/heartbeat 错误 token → 409。"""
        data = await _create_builder_resume(client, auth_headers)
        resume_id = data["id"]

        await client.post(
            f"/api/v1/resumes/{resume_id}/lock", headers=auth_headers,
        )

        resp = await client.post(
            f"/api/v1/resumes/{resume_id}/lock/heartbeat",
            json={"lock_token": "wrong_token_value"},
            headers=auth_headers,
        )
        assert resp.status_code == 409

    async def test_release_lock_success(
        self, client: AsyncClient, auth_headers: dict,
    ):
        """DELETE /resumes/{id}/lock?lock_token=xxx 正确 token → 200。"""
        data = await _create_builder_resume(client, auth_headers)
        resume_id = data["id"]

        acquire_resp = await client.post(
            f"/api/v1/resumes/{resume_id}/lock", headers=auth_headers,
        )
        token = acquire_resp.json()["lock_token"]

        resp = await client.delete(
            f"/api/v1/resumes/{resume_id}/lock?lock_token={token}",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["released"] is True

    async def test_release_lock_wrong_token(
        self, client: AsyncClient, auth_headers: dict,
    ):
        """DELETE /resumes/{id}/lock 错误 token → 409。"""
        data = await _create_builder_resume(client, auth_headers)
        resume_id = data["id"]

        await client.post(
            f"/api/v1/resumes/{resume_id}/lock", headers=auth_headers,
        )

        resp = await client.delete(
            f"/api/v1/resumes/{resume_id}/lock?lock_token=wrong_token",
            headers=auth_headers,
        )
        assert resp.status_code == 409

    async def test_lock_nonexistent_resume(
        self, client: AsyncClient, auth_headers: dict,
    ):
        """POST /resumes/99999/lock → 404（简历不存在）。"""
        resp = await client.post(
            "/api/v1/resumes/99999/lock", headers=auth_headers,
        )
        assert resp.status_code == 404

    async def test_lock_unauthorized(self, client: AsyncClient):
        """无 auth header → 401。"""
        resp = await client.post("/api/v1/resumes/1/lock")
        assert resp.status_code == 401


# ═══════════════════════════════════════════════════════════════
# 2. Builder 工作流集成测试
# ═══════════════════════════════════════════════════════════════


class TestBuilderWorkflowIntegration:
    """端到端 builder 工作流：创建 → 草稿 → 完成 → 状态验证。"""

    async def test_full_builder_workflow(
        self, client: AsyncClient, auth_headers: dict,
    ):
        """完整工作流：创建 → 草稿添加模块 → 完成 → status=ready。"""
        # 1. 创建 builder 简历（带 basic_info）
        data = await _create_builder_resume(
            client, auth_headers,
            modules=[{"module_type": "basic_info", "content": _basic_info_content(), "sort_order": 0}],
        )
        resume_id = data["id"]
        assert data["status"] == "draft"
        assert data["version"] == 1

        # 2. 草稿添加 3 个模块
        draft_resp = await client.put(
            f"/api/v1/resumes/{resume_id}?mode=draft",
            json={
                "modules": [
                    {"module_type": "basic_info", "content": _basic_info_content(), "sort_order": 0},
                    {"module_type": "education", "content": _education_content(), "sort_order": 1},
                    {"module_type": "skills", "content": _skills_content(), "sort_order": 2},
                ],
            },
            headers=auth_headers,
        )
        assert draft_resp.status_code == 200
        assert len(draft_resp.json()["modules"]) == 3
        assert draft_resp.json()["version"] == 1  # draft 不 bump version

        # 3. 完成保存（需 mock 向量化 + L3）
        with patch("services.resume_builder.ensure_indexed", new_callable=AsyncMock) as mock_pr, \
             patch("services.resume_builder.embedding_cache.clear_resume", new_callable=AsyncMock), \
             patch("services.react_agent.memory.build_l3_profile_background", new_callable=AsyncMock):
            mock_pr.return_value = 5
            complete_resp = await client.put(
                f"/api/v1/resumes/{resume_id}?mode=complete",
                json={"version": 1},
                headers=auth_headers,
            )

        assert complete_resp.status_code == 200
        complete_data = complete_resp.json()
        assert complete_data["status"] == "ready"
        assert complete_data["version"] == 2  # complete bumps version
        assert len(complete_data["modules"]) == 3

    async def test_create_with_style(
        self, client: AsyncClient, auth_headers: dict,
    ):
        """POST /resumes/builder 带 style 配置 → 验证 style 已保存。"""
        resp = await client.post(
            "/api/v1/resumes/builder",
            json={"filename": "带样式简历", "style": _default_style()},
            headers=auth_headers,
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["style"] is not None
        assert data["style"]["template_id"] == "default"
        assert data["style"]["accent_color"] == "#2563eb"
        assert data["style"]["font_family"] == "Noto Sans CJK SC"

    async def test_draft_save_preserves_modules(
        self, client: AsyncClient, auth_headers: dict,
    ):
        """草稿保存 3 个模块后 GET /builder 返回全部 3 个（按 sort_order 排序）。"""
        data = await _create_builder_resume(client, auth_headers)
        resume_id = data["id"]

        await client.put(
            f"/api/v1/resumes/{resume_id}?mode=draft",
            json={
                "modules": [
                    {"module_type": "skills", "content": _skills_content(), "sort_order": 2},
                    {"module_type": "basic_info", "content": _basic_info_content(), "sort_order": 0},
                    {"module_type": "education", "content": _education_content(), "sort_order": 1},
                ],
            },
            headers=auth_headers,
        )

        resp = await client.get(
            f"/api/v1/resumes/{resume_id}/builder", headers=auth_headers,
        )
        assert resp.status_code == 200
        modules = resp.json()["modules"]
        assert len(modules) == 3
        # 验证按 sort_order 排序
        assert modules[0]["sort_order"] == 0
        assert modules[0]["module_type"] == "basic_info"
        assert modules[1]["sort_order"] == 1
        assert modules[1]["module_type"] == "education"
        assert modules[2]["sort_order"] == 2
        assert modules[2]["module_type"] == "skills"

    async def test_complete_version_mismatch(
        self, client: AsyncClient, auth_headers: dict, db_session: AsyncSession,
        registered_user: dict,
    ):
        """complete 时 version 不匹配 → 409。"""
        # 直接在 DB 创建 version=3 的 draft 简历
        resume = Resume(
            user_id=registered_user["id"],
            filename="版本冲突测试",
            file_path="",
            parsed_text="",
            chunk_count=0,
            status="draft",
            source="builder",
            version=3,
        )
        db_session.add(resume)
        await db_session.commit()
        await db_session.refresh(resume)

        with patch("services.resume_builder.ensure_indexed", new_callable=AsyncMock), \
             patch("services.resume_builder.embedding_cache.clear_resume", new_callable=AsyncMock):
            resp = await client.put(
                f"/api/v1/resumes/{resume.id}?mode=complete",
                json={"version": 1},  # 真实 version=3
                headers=auth_headers,
            )
        assert resp.status_code == 409

    async def test_draft_ignores_version(
        self, client: AsyncClient, auth_headers: dict, db_session: AsyncSession,
        registered_user: dict,
    ):
        """draft 模式忽略 version（last-write-wins）→ 成功。"""
        resume = Resume(
            user_id=registered_user["id"],
            filename="草稿忽略版本",
            file_path="",
            parsed_text="",
            chunk_count=0,
            status="draft",
            source="builder",
            version=1,
        )
        db_session.add(resume)
        await db_session.commit()
        await db_session.refresh(resume)

        resp = await client.put(
            f"/api/v1/resumes/{resume.id}?mode=draft",
            json={"version": 999, "filename": "改了名字"},  # version 被忽略
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["filename"] == "改了名字"
        assert resp.json()["version"] == 1  # version 不变

    async def test_get_builder_nonexistent(
        self, client: AsyncClient, auth_headers: dict,
    ):
        """GET /resumes/99999/builder → 404。"""
        resp = await client.get(
            "/api/v1/resumes/99999/builder", headers=auth_headers,
        )
        assert resp.status_code == 404

    async def test_get_builder_other_user(
        self, client: AsyncClient, auth_headers: dict,
    ):
        """User A 创建简历，User B 尝试 GET → 404。"""
        data = await _create_builder_resume(client, auth_headers)
        resume_id = data["id"]

        user_b = await _register_second_user(client)
        resp = await client.get(
            f"/api/v1/resumes/{resume_id}/builder", headers=user_b["headers"],
        )
        assert resp.status_code == 404


# ═══════════════════════════════════════════════════════════════
# 3. 模块 Schema 校验测试
# ═══════════════════════════════════════════════════════════════


class TestModuleSchemaValidation:
    """模块 content 校验集成测试（通过 API 触发 pydantic 校验）。"""

    async def test_basic_info_missing_name(
        self, client: AsyncClient, auth_headers: dict,
    ):
        """basic_info 缺少必填 name → 422。"""
        resp = await client.post(
            "/api/v1/resumes/builder",
            json={
                "modules": [
                    {
                        "module_type": "basic_info",
                        "content": {"phone": "13800138000"},  # 缺 name
                        "sort_order": 0,
                    }
                ],
            },
            headers=auth_headers,
        )
        assert resp.status_code == 422

    async def test_education_valid(
        self, client: AsyncClient, auth_headers: dict,
    ):
        """education 合法 entries → 201。"""
        resp = await client.post(
            "/api/v1/resumes/builder",
            json={
                "modules": [
                    {
                        "module_type": "education",
                        "content": _education_content(),
                        "sort_order": 0,
                    }
                ],
            },
            headers=auth_headers,
        )
        assert resp.status_code == 201
        assert len(resp.json()["modules"]) == 1

    async def test_skills_valid(
        self, client: AsyncClient, auth_headers: dict,
    ):
        """skills 合法 categories → 201。"""
        resp = await client.post(
            "/api/v1/resumes/builder",
            json={
                "modules": [
                    {
                        "module_type": "skills",
                        "content": _skills_content(),
                        "sort_order": 0,
                    }
                ],
            },
            headers=auth_headers,
        )
        assert resp.status_code == 201
        assert len(resp.json()["modules"]) == 1

    async def test_all_15_module_types(
        self, client: AsyncClient, auth_headers: dict,
    ):
        """创建含全部 15 种 module_type 的 builder 简历 → 201，GET 返回 15 个模块。"""
        resp = await client.post(
            "/api/v1/resumes/builder",
            json={"filename": "全模块简历", "modules": _all_15_modules()},
            headers=auth_headers,
        )
        assert resp.status_code == 201
        assert len(resp.json()["modules"]) == 15

        resume_id = resp.json()["id"]
        get_resp = await client.get(
            f"/api/v1/resumes/{resume_id}/builder", headers=auth_headers,
        )
        assert get_resp.status_code == 200
        assert len(get_resp.json()["modules"]) == 15

    async def test_module_content_empty_entries(
        self, client: AsyncClient, auth_headers: dict,
    ):
        """education entries=[] 空列表 → 合法（201）。"""
        resp = await client.post(
            "/api/v1/resumes/builder",
            json={
                "modules": [
                    {
                        "module_type": "education",
                        "content": {"entries": []},
                        "sort_order": 0,
                    }
                ],
            },
            headers=auth_headers,
        )
        assert resp.status_code == 201

    async def test_custom_module_valid(
        self, client: AsyncClient, auth_headers: dict,
    ):
        """custom 模块含 title + content → 201。"""
        resp = await client.post(
            "/api/v1/resumes/builder",
            json={
                "modules": [
                    {
                        "module_type": "custom",
                        "content": {"title": "自定义模块", "content": "这是自定义内容"},
                        "sort_order": 0,
                    }
                ],
            },
            headers=auth_headers,
        )
        assert resp.status_code == 201
        assert resp.json()["modules"][0]["content"]["title"] == "自定义模块"


# ═══════════════════════════════════════════════════════════════
# 4. 预览与导出集成测试
# ═══════════════════════════════════════════════════════════════


class TestPreviewExportIntegration:
    """预览与导出端点集成测试（真实工作流 + 缓存 + 守卫）。"""

    def setup_method(self):
        from services.resume_preview import clear_preview_cache
        clear_preview_cache()

    def teardown_method(self):
        from services.resume_preview import clear_preview_cache
        clear_preview_cache()

    async def test_preview_zero_modules(
        self, client: AsyncClient, auth_headers: dict, db_session: AsyncSession,
        registered_user: dict,
    ):
        """零模块简历 → GET /preview → 200 空模板（preview 对零模块不拦截）。"""
        # POST /builder 会预置默认模块，无法创建零模块简历；DB 直插
        resume = Resume(
            user_id=registered_user["id"],
            filename="零模块预览",
            file_path="",
            parsed_text="",
            chunk_count=0,
            status="draft",
            source="builder",
        )
        db_session.add(resume)
        await db_session.commit()
        await db_session.refresh(resume)
        resume_id = resume.id

        resp = await client.get(
            f"/api/v1/resumes/{resume_id}/preview", headers=auth_headers,
        )
        assert resp.status_code == 200
        assert "text/html" in resp.headers.get("content-type", "")

    async def test_preview_with_modules(
        self, client: AsyncClient, auth_headers: dict,
    ):
        """有模块的简历 → GET /preview → 200 + text/html。"""
        data = await _create_builder_resume(
            client, auth_headers,
            modules=[
                {"module_type": "basic_info", "content": _basic_info_content(), "sort_order": 0},
                {"module_type": "education", "content": _education_content(), "sort_order": 1},
            ],
        )
        resume_id = data["id"]

        resp = await client.get(
            f"/api/v1/resumes/{resume_id}/preview", headers=auth_headers,
        )
        assert resp.status_code == 200
        assert "text/html" in resp.headers.get("content-type", "")

    async def test_export_markdown(
        self, client: AsyncClient, auth_headers: dict,
    ):
        """有模块的简历 → GET /export?format=markdown → 200 + text/markdown。"""
        data = await _create_builder_resume(
            client, auth_headers,
            modules=[
                {"module_type": "basic_info", "content": _basic_info_content(), "sort_order": 0},
                {"module_type": "education", "content": _education_content(), "sort_order": 1},
            ],
        )
        resume_id = data["id"]

        resp = await client.get(
            f"/api/v1/resumes/{resume_id}/export?format=markdown",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert "text/markdown" in resp.headers.get("content-type", "")
        assert "张三" in resp.text
        assert "广东海洋大学" in resp.text

    async def test_export_zero_modules(
        self, client: AsyncClient, auth_headers: dict, db_session: AsyncSession,
        registered_user: dict,
    ):
        """source=upload 零模块简历 → GET /export → 422（守卫仅拦截 upload；builder 放行）。"""
        # POST /builder 会预置默认模块，无法创建零模块简历；DB 直插
        resume = Resume(
            user_id=registered_user["id"],
            filename="零模块导出",
            file_path="",
            parsed_text="",
            chunk_count=0,
            status="draft",
            source="upload",
        )
        db_session.add(resume)
        await db_session.commit()
        await db_session.refresh(resume)
        resume_id = resume.id

        resp = await client.get(
            f"/api/v1/resumes/{resume_id}/export?format=markdown",
            headers=auth_headers,
        )
        assert resp.status_code == 422

    async def test_export_invalid_format(
        self, client: AsyncClient, auth_headers: dict,
    ):
        """GET /export?format=docx → 422（不支持格式）。"""
        data = await _create_builder_resume(
            client, auth_headers,
            modules=[{"module_type": "basic_info", "content": _basic_info_content(), "sort_order": 0}],
        )
        resume_id = data["id"]

        resp = await client.get(
            f"/api/v1/resumes/{resume_id}/export?format=docx",
            headers=auth_headers,
        )
        assert resp.status_code == 422

    async def test_preview_cache_hit(
        self, client: AsyncClient, auth_headers: dict,
    ):
        """连续两次 GET /preview → 第二次 X-Cache-Hit: true。"""
        data = await _create_builder_resume(
            client, auth_headers,
            modules=[{"module_type": "basic_info", "content": _basic_info_content(), "sort_order": 0}],
        )
        resume_id = data["id"]

        # 第一次 → cache miss
        resp1 = await client.get(
            f"/api/v1/resumes/{resume_id}/preview", headers=auth_headers,
        )
        assert resp1.status_code == 200
        assert resp1.headers.get("x-cache-hit") == "false"

        # 第二次 → cache hit
        resp2 = await client.get(
            f"/api/v1/resumes/{resume_id}/preview", headers=auth_headers,
        )
        assert resp2.status_code == 200
        assert resp2.headers.get("x-cache-hit") == "true"


# ═══════════════════════════════════════════════════════════════
# 5. 文本反解析端点测试
# ═══════════════════════════════════════════════════════════════


class TestParseToModules:
    """POST /resumes/parse-to-modules 端点集成测试。

    LLM 调用通过 mock services.rag.pipeline.llm_generate 模拟。
    """

    async def test_parse_valid_text(
        self, client: AsyncClient, auth_headers: dict,
    ):
        """合法简历文本 → 200 + modules 列表。"""
        llm_response = json.dumps([
            {"module_type": "basic_info", "content": _basic_info_content(), "sort_order": 0},
            {"module_type": "education", "content": _education_content(), "sort_order": 1},
            {"module_type": "skills", "content": _skills_content(), "sort_order": 2},
        ])

        with patch("services.rag.pipeline.llm_generate", new_callable=AsyncMock, return_value=llm_response):
            resp = await client.post(
                "/api/v1/resumes/parse-to-modules",
                json={"text": "张三，男，24岁，广东海洋大学软件工程本科，精通Python和JavaScript"},
                headers=auth_headers,
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 3
        assert data["modules"][0]["module_type"] == "basic_info"
        assert data["modules"][1]["module_type"] == "education"
        assert data["modules"][2]["module_type"] == "skills"

    async def test_parse_empty_text(
        self, client: AsyncClient, auth_headers: dict,
    ):
        """空文本 → 422。"""
        resp = await client.post(
            "/api/v1/resumes/parse-to-modules",
            json={"text": ""},
            headers=auth_headers,
        )
        assert resp.status_code == 422

    async def test_parse_short_text(
        self, client: AsyncClient, auth_headers: dict,
    ):
        """文本 < 10 字符 → 422。"""
        resp = await client.post(
            "/api/v1/resumes/parse-to-modules",
            json={"text": "短文本"},
            headers=auth_headers,
        )
        assert resp.status_code == 422

    async def test_parse_long_text(
        self, client: AsyncClient, auth_headers: dict,
    ):
        """文本 > 50000 字符 → 422。"""
        resp = await client.post(
            "/api/v1/resumes/parse-to-modules",
            json={"text": "x" * 50001},
            headers=auth_headers,
        )
        assert resp.status_code == 422
