"""T23: resume_builder 新建 + PUT draft（last-write-wins）。

测试范围：
- POST /api/v1/resumes/builder    新建 builder 简历 + 模块
- PUT  /api/v1/resumes/{id}?mode=draft  草稿更新（last-write-wins）
- GET  /api/v1/resumes/{id}/builder     获取简历 + 模块列表
- 归属校验 + 参数校验 + 状态校验 + version 不 bump
"""

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.resume import Resume
from models.resume_module import ResumeModule
from models.user import User


# ═══════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════


def _basic_info_module(**overrides) -> dict:
    """生成 basic_info 模块请求体。"""
    content = {"name": "张三", "phone": "13800138000", "email": "zhangsan@test.com"}
    content.update(overrides)
    return {
        "module_type": "basic_info",
        "content": content,
        "sort_order": 0,
    }


def _education_module(**overrides) -> dict:
    """生成 education 模块请求体。"""
    content = {
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
    content.update(overrides)
    return {
        "module_type": "education",
        "content": content,
        "sort_order": 1,
    }


def _skills_module(**overrides) -> dict:
    """生成 skills 模块请求体。"""
    content = {
        "categories": [
            {"name": "编程语言", "items": ["Python", "JavaScript"]},
            {"name": "框架", "items": ["FastAPI", "React"]},
        ]
    }
    content.update(overrides)
    return {
        "module_type": "skills",
        "content": content,
        "sort_order": 2,
    }


def _work_experience_module(**overrides) -> dict:
    """生成 work_experience 模块请求体。"""
    content = {
        "entries": [
            {
                "company": "测试公司",
                "position": "后端开发实习生",
                "start_date": "2025-06",
                "end_date": "2025-09",
                "description": "负责 API 开发",
            }
        ]
    }
    content.update(overrides)
    return {
        "module_type": "work_experience",
        "content": content,
        "sort_order": 3,
    }


def _default_style() -> dict:
    """生成默认样式。"""
    return {
        "template_id": "default",
        "font_family": "Noto Sans CJK SC",
        "font_size": "14px",
        "line_height": 1.6,
        "spacing": "8px",
        "accent_color": "#2563eb",
    }


async def _create_draft_resume(db: AsyncSession, user_id: int, **overrides) -> Resume:
    """直接在 DB 创建一份 draft 简历（不走 API）。"""
    resume = Resume(
        user_id=user_id,
        filename=overrides.get("filename", "测试简历"),
        file_path="",
        parsed_text="",
        chunk_count=0,
        status=overrides.get("status", "draft"),
        source="builder",
        style=overrides.get("style"),
        version=1,
    )
    db.add(resume)
    await db.commit()
    await db.refresh(resume)
    return resume


async def _create_ready_resume(db: AsyncSession, user_id: int) -> Resume:
    """直接在 DB 创建一份 ready 简历（用于测试 409 场景）。"""
    return await _create_draft_resume(db, user_id, status="ready", filename="已就绪简历")


async def _create_other_user(db: AsyncSession) -> User:
    """创建第二个用户（用于测试归属校验）。"""
    other = User(
        username="other_user",
        email="other@test.com",
        password_hash="dummy_hash",
    )
    db.add(other)
    await db.commit()
    await db.refresh(other)
    return other


# ═══════════════════════════════════════════════════════════
# POST /api/v1/resumes/builder — 新建
# ═══════════════════════════════════════════════════════════


class TestCreateBuilderResume:
    """POST /api/v1/resumes/builder"""

    @pytest.mark.asyncio
    async def test_create_default_modules_preset(
        self, client: AsyncClient, registered_user: dict, auth_headers: dict
    ):
        """不传 modules 时预置 4 个默认核心模块，source=builder, status=draft。"""
        resp = await client.post(
            "/api/v1/resumes/builder",
            json={"filename": "我的简历"},
            headers=auth_headers,
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["filename"] == "我的简历"
        assert data["source"] == "builder"
        assert data["status"] == "draft"
        assert data["version"] == 1
        assert data["style"] is None
        # 预置 4 个默认核心模块（基本信息/教育经历/工作经历/专业技能）
        assert [m["module_type"] for m in data["modules"]] == [
            "basic_info",
            "education",
            "work_experience",
            "skills",
        ]
        assert [m["sort_order"] for m in data["modules"]] == [0, 1, 2, 3]
        # basic_info 占位 name 非空（满足必填校验）
        assert data["modules"][0]["content"]["name"] == "未命名"

    @pytest.mark.asyncio
    async def test_create_with_modules_no_default_preset(
        self, client: AsyncClient, registered_user: dict, auth_headers: dict
    ):
        """显式传 modules 时不预置默认模块。"""
        resp = await client.post(
            "/api/v1/resumes/builder",
            json={"modules": [_skills_module()]},
            headers=auth_headers,
        )
        assert resp.status_code == 201
        data = resp.json()
        assert [m["module_type"] for m in data["modules"]] == ["skills"]

    @pytest.mark.asyncio
    async def test_create_with_modules(
        self, client: AsyncClient, registered_user: dict, auth_headers: dict
    ):
        """带模块创建成功，模块写入 DB。"""
        resp = await client.post(
            "/api/v1/resumes/builder",
            json={
                "filename": "简历带模块",
                "modules": [
                    _basic_info_module(),
                    _education_module(),
                    _skills_module(),
                ],
            },
            headers=auth_headers,
        )
        assert resp.status_code == 201
        data = resp.json()
        assert len(data["modules"]) == 3
        # 验证模块类型和排序
        assert data["modules"][0]["module_type"] == "basic_info"
        assert data["modules"][0]["sort_order"] == 0
        assert data["modules"][1]["module_type"] == "education"
        assert data["modules"][1]["sort_order"] == 1
        assert data["modules"][2]["module_type"] == "skills"
        assert data["modules"][2]["sort_order"] == 2
        # 验证 content 正确
        assert data["modules"][0]["content"]["name"] == "张三"

    @pytest.mark.asyncio
    async def test_copy_resume_creates_new_draft(
        self, client: AsyncClient, registered_user: dict, auth_headers: dict
    ):
        """G 多语言版本：POST /resumes/{id}/copy → 新草稿副本，模块一致，原稿不变。"""
        created = await client.post(
            "/api/v1/resumes/builder",
            json={"filename": "我的简历"},
            headers=auth_headers,
        )
        src_id = created.json()["id"]
        resp = await client.post(
            f"/api/v1/resumes/{src_id}/copy?language=en", headers=auth_headers
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["id"] != src_id
        assert data["status"] == "draft"
        assert data["version"] == 1
        assert "副本" in data["filename"]
        # 多语言版本：language 透传 + family 归属（源无 family → 副本以源为族根）
        assert data["language"] == "en"
        assert data["family_id"] == src_id
        # 模块完整复制（预置 4 个核心模块）
        assert [m["module_type"] for m in data["modules"]] == [
            "basic_info",
            "education",
            "work_experience",
            "skills",
        ]

    @pytest.mark.asyncio
    async def test_copy_resume_isolated(
        self, client: AsyncClient, registered_user: dict, auth_headers: dict
    ):
        """非本人复制他人简历 → 404（C4 越权隔离）。"""
        created = await client.post(
            "/api/v1/resumes/builder",
            json={"filename": "私有简历"},
            headers=auth_headers,
        )
        src_id = created.json()["id"]
        other = {"username": "othercp", "email": "othercp@example.com", "password": "Test1234!", "password_confirm": "Test1234!"}
        await client.post("/api/v1/auth/send-code", json={"email": other["email"]})
        from services.verification_service import _CODE_KEY_PREFIX, _in_memory_codes

        code = _in_memory_codes.get(f"{_CODE_KEY_PREFIX}{other['email']}")["code"]
        await client.post("/api/v1/auth/register", json={**other, "verification_code": code})
        login = await client.post("/api/v1/auth/login", json={"email": other["email"], "password": other["password"]})
        other_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        resp = await client.post(f"/api/v1/resumes/{src_id}/copy", headers=other_headers)
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_resume_family_list(
        self, client: AsyncClient, registered_user: dict, auth_headers: dict
    ):
        """G 多语言版本：GET /resumes/{id}/family 返回同族版本（含自身），源/副本可互换查。"""
        created = await client.post(
            "/api/v1/resumes/builder",
            json={"filename": "我的简历"},
            headers=auth_headers,
        )
        src_id = created.json()["id"]
        # 复制出英文版（family 继承源为族根）
        copied = await client.post(
            f"/api/v1/resumes/{src_id}/copy?language=en", headers=auth_headers
        )
        assert copied.status_code == 201
        copy_id = copied.json()["id"]

        # 从源查 family：含源 + 英文副本，按 created_at 升序
        resp = await client.get(f"/api/v1/resumes/{src_id}/family", headers=auth_headers)
        assert resp.status_code == 200
        items = resp.json()
        assert [i["id"] for i in items] == [src_id, copy_id]
        assert items[0]["language"] is None  # 源未标注
        assert items[1]["language"] == "en"

        # 从副本查 family：同族
        resp2 = await client.get(f"/api/v1/resumes/{copy_id}/family", headers=auth_headers)
        assert [i["id"] for i in resp2.json()] == [src_id, copy_id]

    @pytest.mark.asyncio
    async def test_create_with_style(
        self, client: AsyncClient, registered_user: dict, auth_headers: dict
    ):
        """带样式创建成功，style JSON 存入 DB。"""
        resp = await client.post(
            "/api/v1/resumes/builder",
            json={
                "filename": "带样式简历",
                "style": _default_style(),
            },
            headers=auth_headers,
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["style"] is not None
        assert data["style"]["template_id"] == "default"
        assert data["style"]["accent_color"] == "#2563eb"

    @pytest.mark.asyncio
    async def test_create_default_filename(
        self, client: AsyncClient, registered_user: dict, auth_headers: dict
    ):
        """不传 filename 时使用默认值。"""
        resp = await client.post(
            "/api/v1/resumes/builder",
            json={},
            headers=auth_headers,
        )
        assert resp.status_code == 201
        assert resp.json()["filename"] == "未命名简历"

    @pytest.mark.asyncio
    async def test_create_invalid_module_content(
        self, client: AsyncClient, registered_user: dict, auth_headers: dict
    ):
        """模块 content 校验失败 → 422。basic_info 必须有 name 字段。"""
        resp = await client.post(
            "/api/v1/resumes/builder",
            json={
                "modules": [
                    {
                        "module_type": "basic_info",
                        "content": {},  # 缺少必填 name
                        "sort_order": 0,
                    }
                ],
            },
            headers=auth_headers,
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_create_unknown_module_type(
        self, client: AsyncClient, registered_user: dict, auth_headers: dict
    ):
        """未知 module_type → 422（Pydantic 枚举校验）。"""
        resp = await client.post(
            "/api/v1/resumes/builder",
            json={
                "modules": [
                    {
                        "module_type": "unknown_type",
                        "content": {"name": "测试"},
                        "sort_order": 0,
                    }
                ],
            },
            headers=auth_headers,
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_create_no_auth(self, client: AsyncClient):
        """未登录 → 401。"""
        resp = await client.post(
            "/api/v1/resumes/builder",
            json={"filename": "无权限"},
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_create_all_fifteen_module_types(
        self, client: AsyncClient, registered_user: dict, auth_headers: dict
    ):
        """所有 15 种 module_type 均可创建。"""
        modules = [
            {"module_type": "basic_info", "content": {"name": "测试"}, "sort_order": 0},
            {"module_type": "education", "content": {"entries": []}, "sort_order": 1},
            {"module_type": "work_experience", "content": {"entries": []}, "sort_order": 2},
            {"module_type": "project_experience", "content": {"entries": []}, "sort_order": 3},
            {"module_type": "skills", "content": {"categories": []}, "sort_order": 4},
            {"module_type": "language", "content": {"entries": []}, "sort_order": 5},
            {"module_type": "honors", "content": {"entries": []}, "sort_order": 6},
            {"module_type": "certificates", "content": {"entries": []}, "sort_order": 7},
            {"module_type": "interests", "content": {"items": ["阅读"]}, "sort_order": 8},
            {"module_type": "club_activities", "content": {"entries": []}, "sort_order": 9},
            {"module_type": "publications", "content": {"entries": []}, "sort_order": 10},
            {"module_type": "recommendation", "content": {"entries": []}, "sort_order": 11},
            {"module_type": "social_links", "content": {}, "sort_order": 12},
            {"module_type": "other", "content": {"content": "其他内容"}, "sort_order": 13},
            {"module_type": "custom", "content": {"title": "自定义", "content": "内容"}, "sort_order": 14},
        ]
        resp = await client.post(
            "/api/v1/resumes/builder",
            json={"filename": "全模块简历", "modules": modules},
            headers=auth_headers,
        )
        assert resp.status_code == 201
        assert len(resp.json()["modules"]) == 15


# ═══════════════════════════════════════════════════════════
# PUT /api/v1/resumes/{id}?mode=draft — 草稿更新
# ═══════════════════════════════════════════════════════════


class TestUpdateResumeDraft:
    """PUT /api/v1/resumes/{id}?mode=draft"""

    @pytest.mark.asyncio
    async def test_update_modules_full_replacement(
        self, client: AsyncClient, registered_user: dict, auth_headers: dict, db_session: AsyncSession
    ):
        """全量替换模块：旧模块删除，新模块插入。"""
        resume = await _create_draft_resume(db_session, registered_user["id"])

        resp = await client.put(
            f"/api/v1/resumes/{resume.id}?mode=draft",
            json={
                "modules": [
                    _basic_info_module(name="李四"),
                    _education_module(),
                ],
            },
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["modules"]) == 2
        assert data["modules"][0]["content"]["name"] == "李四"

        # 验证 DB 中旧模块已删除
        result = await db_session.execute(
            select(ResumeModule).where(ResumeModule.resume_id == resume.id)
        )
        db_modules = list(result.scalars().all())
        assert len(db_modules) == 2

    @pytest.mark.asyncio
    async def test_update_style_only(
        self, client: AsyncClient, registered_user: dict, auth_headers: dict, db_session: AsyncSession
    ):
        """仅更新样式，不影响模块。"""
        resume = await _create_draft_resume(db_session, registered_user["id"])

        resp = await client.put(
            f"/api/v1/resumes/{resume.id}?mode=draft",
            json={"style": _default_style()},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["style"] is not None
        assert data["style"]["accent_color"] == "#2563eb"

    @pytest.mark.asyncio
    async def test_update_filename_only(
        self, client: AsyncClient, registered_user: dict, auth_headers: dict, db_session: AsyncSession
    ):
        """仅更新文件名。"""
        resume = await _create_draft_resume(db_session, registered_user["id"])

        resp = await client.put(
            f"/api/v1/resumes/{resume.id}?mode=draft",
            json={"filename": "新名字"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["filename"] == "新名字"

    @pytest.mark.asyncio
    async def test_update_does_not_bump_version(
        self, client: AsyncClient, registered_user: dict, auth_headers: dict, db_session: AsyncSession
    ):
        """草稿更新不 bump version（last-write-wins）。"""
        resume = await _create_draft_resume(db_session, registered_user["id"])
        assert resume.version == 1

        resp = await client.put(
            f"/api/v1/resumes/{resume.id}?mode=draft",
            json={"filename": "改了名字"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["version"] == 1  # version 不变

    @pytest.mark.asyncio
    async def test_update_ready_resume_allowed(
        self, client: AsyncClient, registered_user: dict, auth_headers: dict, db_session: AsyncSession
    ):
        """ready 简历也可草稿保存（编辑上传/已完成简历时自动保存应可用）。"""
        resume = await _create_ready_resume(db_session, registered_user["id"])

        resp = await client.put(
            f"/api/v1/resumes/{resume.id}?mode=draft",
            json={"filename": "尝试修改"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["filename"] == "尝试修改"

    @pytest.mark.asyncio
    async def test_update_processing_resume_409(
        self, client: AsyncClient, registered_user: dict, auth_headers: dict, db_session: AsyncSession
    ):
        """processing 状态简历不允许草稿保存 → 409。"""
        resume = await _create_draft_resume(
            db_session, registered_user["id"], status="processing"
        )

        resp = await client.put(
            f"/api/v1/resumes/{resume.id}?mode=draft",
            json={"filename": "尝试修改"},
            headers=auth_headers,
        )
        assert resp.status_code == 409
        assert "仅草稿或已就绪简历" in resp.json()["error"]["message"]

    @pytest.mark.asyncio
    async def test_update_nonexistent_resume_404(
        self, client: AsyncClient, auth_headers: dict
    ):
        """简历不存在 → 404。"""
        resp = await client.put(
            "/api/v1/resumes/99999?mode=draft",
            json={"filename": "不存在"},
            headers=auth_headers,
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_update_other_user_resume_404(
        self, client: AsyncClient, registered_user: dict, auth_headers: dict, db_session: AsyncSession
    ):
        """别人的简历 → 404。"""
        # 创建另一个用户及其简历
        other_user = await _create_other_user(db_session)
        other_resume = Resume(
            user_id=other_user.id,
            filename="别人的简历",
            file_path="",
            parsed_text="",
            status="draft",
            source="builder",
        )
        db_session.add(other_resume)
        await db_session.commit()

        resp = await client.put(
            f"/api/v1/resumes/{other_resume.id}?mode=draft",
            json={"filename": "偷改"},
            headers=auth_headers,
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_draft_save_basic_info_missing_name_is_coerced(
        self, client: AsyncClient, registered_user: dict, auth_headers: dict, db_session: AsyncSession
    ):
        """草稿保存 basic_info 缺 name 时兜底补占位名，允许保存编辑中间态。

        用户清空姓名尚未重填时触发 5s 自动保存草稿，name 必填校验会 422，
        草稿本就是中间态，应容忍不完整输入（保存并完成时仍严格校验）。
        """
        resume = await _create_draft_resume(db_session, registered_user["id"])

        resp = await client.put(
            f"/api/v1/resumes/{resume.id}?mode=draft",
            json={
                "modules": [
                    {
                        "module_type": "basic_info",
                        "content": {},  # 缺必填 name → 草稿兜底补占位
                        "sort_order": 0,
                    }
                ],
            },
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["modules"][0]["content"]["name"] == "未命名"

    @pytest.mark.asyncio
    async def test_draft_save_blank_entry_is_removed(
        self, client: AsyncClient, registered_user: dict, auth_headers: dict, db_session: AsyncSession
    ):
        """草稿保存时移除全空条目，容忍编辑中间态（刚点"添加条目"还没填）。"""
        resume = await _create_draft_resume(db_session, registered_user["id"])

        resp = await client.put(
            f"/api/v1/resumes/{resume.id}?mode=draft",
            json={
                "modules": [
                    {
                        "module_type": "education",
                        "content": {"entries": [{}]},
                        "sort_order": 0,
                    }
                ],
            },
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["modules"][0]["content"]["entries"] == []

    @pytest.mark.asyncio
    async def test_draft_save_blank_skill_category_is_removed(
        self, client: AsyncClient, registered_user: dict, auth_headers: dict, db_session: AsyncSession
    ):
        """草稿保存时移除空技能分类，容忍编辑中间态。"""
        resume = await _create_draft_resume(db_session, registered_user["id"])

        resp = await client.put(
            f"/api/v1/resumes/{resume.id}?mode=draft",
            json={
                "modules": [
                    {
                        "module_type": "skills",
                        "content": {"categories": [{"name": "", "items": []}]},
                        "sort_order": 0,
                    }
                ],
            },
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["modules"][0]["content"]["categories"] == []

    @pytest.mark.asyncio
    async def test_update_empty_modules(
        self, client: AsyncClient, registered_user: dict, auth_headers: dict, db_session: AsyncSession
    ):
        """传空模块列表 → 全部删除。"""
        resume = await _create_draft_resume(db_session, registered_user["id"])

        resp = await client.put(
            f"/api/v1/resumes/{resume.id}?mode=draft",
            json={"modules": []},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["modules"] == []

    @pytest.mark.asyncio
    async def test_update_no_auth(self, client: AsyncClient, db_session: AsyncSession, registered_user: dict):
        """未登录 → 401。"""
        resume = await _create_draft_resume(db_session, registered_user["id"])

        resp = await client.put(
            f"/api/v1/resumes/{resume.id}?mode=draft",
            json={"filename": "无权限"},
        )
        assert resp.status_code == 401


# ═══════════════════════════════════════════════════════════
# PUT mode 参数校验
# ═══════════════════════════════════════════════════════════


class TestUpdateModeParameter:
    """PUT /api/v1/resumes/{id} 的 mode 参数。"""

    @pytest.mark.asyncio
    async def test_mode_complete_requires_version(
        self, client: AsyncClient, registered_user: dict, auth_headers: dict, db_session: AsyncSession
    ):
        """mode=complete 已在 T24 实现，缺 version → 422。"""
        resume = await _create_draft_resume(db_session, registered_user["id"])

        resp = await client.put(
            f"/api/v1/resumes/{resume.id}?mode=complete",
            json={"filename": "尝试完成"},
            headers=auth_headers,
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_invalid_mode_returns_422(
        self, client: AsyncClient, registered_user: dict, auth_headers: dict, db_session: AsyncSession
    ):
        """不支持的 mode → 422。"""
        resume = await _create_draft_resume(db_session, registered_user["id"])

        resp = await client.put(
            f"/api/v1/resumes/{resume.id}?mode=invalid",
            json={"filename": "无效模式"},
            headers=auth_headers,
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_missing_mode_returns_422(
        self, client: AsyncClient, registered_user: dict, auth_headers: dict, db_session: AsyncSession
    ):
        """缺少 mode 参数 → 422。"""
        resume = await _create_draft_resume(db_session, registered_user["id"])

        resp = await client.put(
            f"/api/v1/resumes/{resume.id}",
            json={"filename": "无 mode"},
            headers=auth_headers,
        )
        assert resp.status_code == 422


# ═══════════════════════════════════════════════════════════
# GET /api/v1/resumes/{id}/builder — 获取简历+模块
# ═══════════════════════════════════════════════════════════


class TestGetBuilderResume:
    """GET /api/v1/resumes/{id}/builder"""

    @pytest.mark.asyncio
    async def test_get_resume_with_modules(
        self, client: AsyncClient, registered_user: dict, auth_headers: dict, db_session: AsyncSession
    ):
        """获取简历 + 模块列表。"""
        # 先通过 API 创建带模块的简历
        create_resp = await client.post(
            "/api/v1/resumes/builder",
            json={
                "filename": "查询测试",
                "modules": [_basic_info_module(), _skills_module()],
            },
            headers=auth_headers,
        )
        assert create_resp.status_code == 201
        resume_id = create_resp.json()["id"]

        # 查询
        resp = await client.get(
            f"/api/v1/resumes/{resume_id}/builder",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == resume_id
        assert data["filename"] == "查询测试"
        assert data["source"] == "builder"
        assert len(data["modules"]) == 2

    @pytest.mark.asyncio
    async def test_get_resume_no_modules(
        self, client: AsyncClient, registered_user: dict, auth_headers: dict, db_session: AsyncSession
    ):
        """无模块的简历返回空列表。"""
        resume = await _create_draft_resume(db_session, registered_user["id"])

        resp = await client.get(
            f"/api/v1/resumes/{resume.id}/builder",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["modules"] == []

    @pytest.mark.asyncio
    async def test_get_nonexistent_resume_404(
        self, client: AsyncClient, auth_headers: dict
    ):
        """简历不存在 → 404。"""
        resp = await client.get(
            "/api/v1/resumes/99999/builder",
            headers=auth_headers,
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_get_other_user_resume_404(
        self, client: AsyncClient, registered_user: dict, auth_headers: dict, db_session: AsyncSession
    ):
        """别人的简历 → 404。"""
        other_user = await _create_other_user(db_session)
        other_resume = Resume(
            user_id=other_user.id,
            filename="别人的",
            file_path="",
            parsed_text="",
            status="draft",
            source="builder",
        )
        db_session.add(other_resume)
        await db_session.commit()

        resp = await client.get(
            f"/api/v1/resumes/{other_resume.id}/builder",
            headers=auth_headers,
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_get_no_auth(self, client: AsyncClient, db_session: AsyncSession, registered_user: dict):
        """未登录 → 401。"""
        resume = await _create_draft_resume(db_session, registered_user["id"])

        resp = await client.get(f"/api/v1/resumes/{resume.id}/builder")
        assert resp.status_code == 401


# ═══════════════════════════════════════════════════════════
# 草稿隔离 — draft 不进问答
# ═══════════════════════════════════════════════════════════


class TestDraftIsolation:
    """草稿简历不进入问答/分析流程（status != ready）。"""

    @pytest.mark.asyncio
    async def test_draft_resume_not_ready(
        self, client: AsyncClient, registered_user: dict, auth_headers: dict
    ):
        """新建 builder 简历的 status 应为 draft，不是 ready。"""
        resp = await client.post(
            "/api/v1/resumes/builder",
            json={"filename": "草稿"},
            headers=auth_headers,
        )
        assert resp.status_code == 201
        assert resp.json()["status"] == "draft"

    @pytest.mark.asyncio
    async def test_draft_resume_cannot_analyze(
        self, client: AsyncClient, registered_user: dict, auth_headers: dict
    ):
        """draft 简历不能调用分析接口 → 409。"""
        create_resp = await client.post(
            "/api/v1/resumes/builder",
            json={"filename": "草稿"},
            headers=auth_headers,
        )
        resume_id = create_resp.json()["id"]

        # 尝试分析 → 409（status != ready）
        resp = await client.post(
            f"/api/v1/resumes/{resume_id}/analyze",
            json={"analysis_type": "summary"},
            headers=auth_headers,
        )
        assert resp.status_code == 409

    @pytest.mark.asyncio
    async def test_draft_resume_cannot_get_chunks(
        self, client: AsyncClient, registered_user: dict, auth_headers: dict
    ):
        """draft 简历不能查分块 → 409。"""
        create_resp = await client.post(
            "/api/v1/resumes/builder",
            json={"filename": "草稿"},
            headers=auth_headers,
        )
        resume_id = create_resp.json()["id"]

        resp = await client.get(
            f"/api/v1/resumes/{resume_id}/chunks",
            headers=auth_headers,
        )
        assert resp.status_code == 409


# ═══════════════════════════════════════════════════════════
# 模块排序
# ═══════════════════════════════════════════════════════════


class TestModuleSortOrder:
    """模块排序逻辑。"""

    @pytest.mark.asyncio
    async def test_custom_sort_order(
        self, client: AsyncClient, registered_user: dict, auth_headers: dict
    ):
        """自定义 sort_order 被正确保存。"""
        resp = await client.post(
            "/api/v1/resumes/builder",
            json={
                "modules": [
                    {"module_type": "skills", "content": {"categories": []}, "sort_order": 5},
                    {"module_type": "basic_info", "content": {"name": "测试"}, "sort_order": 1},
                    {"module_type": "education", "content": {"entries": []}, "sort_order": 3},
                ],
            },
            headers=auth_headers,
        )
        assert resp.status_code == 201
        data = resp.json()
        # 按 sort_order 排序返回
        assert data["modules"][0]["sort_order"] == 1
        assert data["modules"][1]["sort_order"] == 3
        assert data["modules"][2]["sort_order"] == 5

    @pytest.mark.asyncio
    async def test_reorder_via_update(
        self, client: AsyncClient, registered_user: dict, auth_headers: dict, db_session: AsyncSession
    ):
        """更新时重新排序。"""
        # 创建
        create_resp = await client.post(
            "/api/v1/resumes/builder",
            json={
                "modules": [
                    {"module_type": "basic_info", "content": {"name": "测试"}, "sort_order": 0},
                    {"module_type": "education", "content": {"entries": []}, "sort_order": 1},
                ],
            },
            headers=auth_headers,
        )
        resume_id = create_resp.json()["id"]

        # 更新排序
        resp = await client.put(
            f"/api/v1/resumes/{resume_id}?mode=draft",
            json={
                "modules": [
                    {"module_type": "education", "content": {"entries": []}, "sort_order": 0},
                    {"module_type": "basic_info", "content": {"name": "测试"}, "sort_order": 1},
                ],
            },
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["modules"][0]["module_type"] == "education"
        assert data["modules"][1]["module_type"] == "basic_info"


# ═══════════════════════════════════════════════════════════
# 连续草稿更新
# ═══════════════════════════════════════════════════════════


class TestConsecutiveDraftUpdates:
    """连续草稿更新（模拟前端 5s 自动保存）。"""

    @pytest.mark.asyncio
    async def test_multiple_updates_no_version_change(
        self, client: AsyncClient, registered_user: dict, auth_headers: dict, db_session: AsyncSession
    ):
        """多次草稿更新 version 始终为 1。"""
        resume = await _create_draft_resume(db_session, registered_user["id"])

        for i in range(3):
            resp = await client.put(
                f"/api/v1/resumes/{resume.id}?mode=draft",
                json={"filename": f"第{i+1}次修改"},
                headers=auth_headers,
            )
            assert resp.status_code == 200
            assert resp.json()["version"] == 1

    @pytest.mark.asyncio
    async def test_update_add_then_remove_modules(
        self, client: AsyncClient, registered_user: dict, auth_headers: dict, db_session: AsyncSession
    ):
        """先加模块，再删模块。"""
        resume = await _create_draft_resume(db_session, registered_user["id"])

        # 加模块
        resp = await client.put(
            f"/api/v1/resumes/{resume.id}?mode=draft",
            json={"modules": [_basic_info_module(), _education_module(), _skills_module()]},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert len(resp.json()["modules"]) == 3

        # 删到只剩一个
        resp = await client.put(
            f"/api/v1/resumes/{resume.id}?mode=draft",
            json={"modules": [_basic_info_module()]},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert len(resp.json()["modules"]) == 1
        assert resp.json()["modules"][0]["module_type"] == "basic_info"

    @pytest.mark.asyncio
    async def test_update_style_then_modules_separately(
        self, client: AsyncClient, registered_user: dict, auth_headers: dict, db_session: AsyncSession
    ):
        """分两次更新：先样式，后模块。"""
        resume = await _create_draft_resume(db_session, registered_user["id"])

        # 先更新样式
        resp = await client.put(
            f"/api/v1/resumes/{resume.id}?mode=draft",
            json={"style": _default_style()},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["style"]["accent_color"] == "#2563eb"

        # 后更新模块
        resp = await client.put(
            f"/api/v1/resumes/{resume.id}?mode=draft",
            json={"modules": [_basic_info_module()]},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["modules"]) == 1
        # 样式应保留
        assert data["style"]["accent_color"] == "#2563eb"
