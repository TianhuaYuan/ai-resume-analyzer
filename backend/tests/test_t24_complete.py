"""T24: 保存并完成（合并 parsed_text + drop/rebuild Chroma + ready + L3）。

测试范围：
- PUT /api/v1/resumes/{id}?mode=complete  保存并完成
- 乐观锁校验（version 不匹配 → 409）
- 状态校验（processing/failed → 409）
- 模块替换 + parsed_text 生成
- Chroma 重建（mock process_resume）
- L3 触发（mock build_l3_profile_background）
- 幂等性（re-complete ready 简历）
- 归属校验
- _merge_modules_to_text 单元测试
- draft 模式向后兼容
"""

from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.resume import Resume
from models.resume_module import ResumeModule
from models.user import User
from services.resume_builder import _merge_modules_to_text


# ═══════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════


def _basic_info_module(**overrides) -> dict:
    content = {"name": "张三", "phone": "13800138000", "email": "zhangsan@test.com"}
    content.update(overrides)
    return {"module_type": "basic_info", "content": content, "sort_order": 0}


def _education_module(**overrides) -> dict:
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
    return {"module_type": "education", "content": content, "sort_order": 1}


def _skills_module(**overrides) -> dict:
    content = {
        "categories": [
            {"name": "编程语言", "items": ["Python", "JavaScript"]},
            {"name": "框架", "items": ["FastAPI", "React"]},
        ]
    }
    content.update(overrides)
    return {"module_type": "skills", "content": content, "sort_order": 2}


def _work_experience_module(**overrides) -> dict:
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
    return {"module_type": "work_experience", "content": content, "sort_order": 3}


def _default_modules() -> list[dict]:
    return [_basic_info_module(), _education_module(), _skills_module()]


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
        version=overrides.get("version", 1),
    )
    db.add(resume)
    await db.commit()
    await db.refresh(resume)
    return resume


async def _create_draft_with_modules(
    db: AsyncSession, user_id: int, modules: list[dict] | None = None
) -> tuple[Resume, list[ResumeModule]]:
    """创建 draft 简历 + 模块。"""
    resume = await _create_draft_resume(db, user_id)
    created = []
    if modules:
        for mod_data in modules:
            module = ResumeModule(
                resume_id=resume.id,
                module_type=mod_data["module_type"],
                content=mod_data["content"],
                sort_order=mod_data.get("sort_order", 0),
            )
            db.add(module)
            created.append(module)
        await db.commit()
        for m in created:
            await db.refresh(m)
    return resume, created


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
# _merge_modules_to_text 单元测试
# ═══════════════════════════════════════════════════════════


class TestMergeModulesToText:
    """_merge_modules_to_text — 模块列表 → 纯文本。"""

    def test_basic_info_to_text(self):
        """basic_info 模块转文本包含姓名等字段。"""
        mod = ResumeModule(
            module_type="basic_info",
            content={"name": "张三", "phone": "13800138000"},
            sort_order=0,
        )
        text = _merge_modules_to_text([mod])
        assert "个人简介" in text
        assert "姓名: 张三" in text
        assert "手机: 13800138000" in text

    def test_education_to_text(self):
        """education 模块转文本包含学校等字段。"""
        mod = ResumeModule(
            module_type="education",
            content={"entries": [{"school": "广东海洋大学", "major": "软件工程"}]},
            sort_order=0,
        )
        text = _merge_modules_to_text([mod])
        assert "教育背景" in text
        assert "广东海洋大学" in text
        assert "软件工程" in text

    def test_skills_to_text(self):
        """skills 模块转文本包含分类和技能项。"""
        mod = ResumeModule(
            module_type="skills",
            content={
                "categories": [
                    {"name": "编程语言", "items": ["Python", "JavaScript"]},
                ]
            },
            sort_order=0,
        )
        text = _merge_modules_to_text([mod])
        assert "专业技能" in text
        assert "编程语言: Python, JavaScript" in text

    def test_multiple_modules_to_text(self):
        """多模块合并，每个模块有独立节段标题。"""
        mods = [
            ResumeModule(module_type="basic_info", content={"name": "李四"}, sort_order=0),
            ResumeModule(
                module_type="education",
                content={"entries": [{"school": "北京大学"}]},
                sort_order=1,
            ),
            ResumeModule(
                module_type="skills",
                content={"categories": [{"name": "编程语言", "items": ["Go"]}]},
                sort_order=2,
            ),
        ]
        text = _merge_modules_to_text(mods)
        assert "个人简介" in text
        assert "教育背景" in text
        assert "专业技能" in text
        # 模块之间用双换行分隔
        assert "\n\n" in text

    def test_empty_modules_to_text(self):
        """空模块列表 → 空字符串。"""
        assert _merge_modules_to_text([]) == ""

    def test_module_with_empty_content_skipped(self):
        """content 为空值的模块不生成文本。"""
        mod = ResumeModule(
            module_type="basic_info",
            content={"name": "王五", "phone": None, "email": ""},
            sort_order=0,
        )
        text = _merge_modules_to_text([mod])
        assert "姓名: 王五" in text
        # None 和空字符串的字段不出现
        assert "手机" not in text
        assert "邮箱" not in text


# ═══════════════════════════════════════════════════════════
# PUT /api/v1/resumes/{id}?mode=complete — 成功路径
# ═══════════════════════════════════════════════════════════


class TestCompleteSuccess:
    """PUT mode=complete 成功路径。"""

    @pytest.mark.asyncio
    async def test_complete_draft_to_ready(
        self, client: AsyncClient, registered_user: dict, auth_headers: dict, db_session: AsyncSession
    ):
        """draft → ready，version 1→2，parsed_text 非空。"""
        resume, _ = await _create_draft_with_modules(
            db_session, registered_user["id"], _default_modules()
        )

        with patch("services.resume_builder.process_resume", new_callable=AsyncMock) as mock_pr, \
             patch("services.resume_builder.embedding_cache.clear_resume", new_callable=AsyncMock), \
             patch("services.react_agent.memory.build_l3_profile_background", new_callable=AsyncMock):
            mock_pr.return_value = 5

            resp = await client.put(
                f"/api/v1/resumes/{resume.id}?mode=complete",
                json={"version": 1},
                headers=auth_headers,
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ready"
        assert data["version"] == 2  # version bumped
        assert len(data["modules"]) == 3

    @pytest.mark.asyncio
    async def test_complete_with_new_modules(
        self, client: AsyncClient, registered_user: dict, auth_headers: dict, db_session: AsyncSession
    ):
        """complete 时全量替换模块。"""
        resume, _ = await _create_draft_with_modules(
            db_session, registered_user["id"], [_basic_info_module()]
        )

        with patch("services.resume_builder.process_resume", new_callable=AsyncMock) as mock_pr, \
             patch("services.resume_builder.embedding_cache.clear_resume", new_callable=AsyncMock), \
             patch("services.react_agent.memory.build_l3_profile_background", new_callable=AsyncMock):
            mock_pr.return_value = 3

            resp = await client.put(
                f"/api/v1/resumes/{resume.id}?mode=complete",
                json={
                    "version": 1,
                    "modules": [
                        _basic_info_module(name="李四"),
                        _work_experience_module(),
                    ],
                },
                headers=auth_headers,
            )

        assert resp.status_code == 200
        data = resp.json()
        assert len(data["modules"]) == 2
        assert data["modules"][0]["content"]["name"] == "李四"
        assert data["modules"][1]["module_type"] == "work_experience"

    @pytest.mark.asyncio
    async def test_complete_re_complete(
        self, client: AsyncClient, registered_user: dict, auth_headers: dict, db_session: AsyncSession
    ):
        """ready → ready（重新完成，version=2 → 3）。"""
        resume, _ = await _create_draft_with_modules(
            db_session, registered_user["id"], _default_modules()
        )
        # 先手动设为 ready + version=2
        resume.status = "ready"
        resume.version = 2
        await db_session.commit()

        with patch("services.resume_builder.process_resume", new_callable=AsyncMock) as mock_pr, \
             patch("services.resume_builder.embedding_cache.clear_resume", new_callable=AsyncMock), \
             patch("services.react_agent.memory.build_l3_profile_background", new_callable=AsyncMock):
            mock_pr.return_value = 4

            resp = await client.put(
                f"/api/v1/resumes/{resume.id}?mode=complete",
                json={"version": 2, "filename": "改了名字"},
                headers=auth_headers,
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ready"
        assert data["version"] == 3
        assert data["filename"] == "改了名字"

    @pytest.mark.asyncio
    async def test_complete_empty_modules(
        self, client: AsyncClient, registered_user: dict, auth_headers: dict, db_session: AsyncSession
    ):
        """无模块 complete → parsed_text 空，chunk_count=0。"""
        resume = await _create_draft_resume(db_session, registered_user["id"])

        with patch("services.resume_builder.process_resume", new_callable=AsyncMock) as mock_pr, \
             patch("services.resume_builder.embedding_cache.clear_resume", new_callable=AsyncMock), \
             patch("services.react_agent.memory.build_l3_profile_background", new_callable=AsyncMock):
            mock_pr.return_value = 0

            resp = await client.put(
                f"/api/v1/resumes/{resume.id}?mode=complete",
                json={"version": 1},
                headers=auth_headers,
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ready"
        assert data["version"] == 2
        assert data["modules"] == []

    @pytest.mark.asyncio
    async def test_complete_filename_and_style_update(
        self, client: AsyncClient, registered_user: dict, auth_headers: dict, db_session: AsyncSession
    ):
        """complete 同时更新 filename 和 style。"""
        resume, _ = await _create_draft_with_modules(
            db_session, registered_user["id"], [_basic_info_module()]
        )

        new_style = {
            "template_id": "business",
            "font_family": "SimSun",
            "font_size": "16px",
            "line_height": 1.8,
            "spacing": "12px",
            "accent_color": "#1e40af",
        }

        with patch("services.resume_builder.process_resume", new_callable=AsyncMock) as mock_pr, \
             patch("services.resume_builder.embedding_cache.clear_resume", new_callable=AsyncMock), \
             patch("services.react_agent.memory.build_l3_profile_background", new_callable=AsyncMock):
            mock_pr.return_value = 2

            resp = await client.put(
                f"/api/v1/resumes/{resume.id}?mode=complete",
                json={"version": 1, "filename": "新名字", "style": new_style},
                headers=auth_headers,
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["filename"] == "新名字"
        assert data["style"]["template_id"] == "business"
        assert data["style"]["font_size"] == "16px"


# ═══════════════════════════════════════════════════════════
# PUT mode=complete — 错误路径
# ═══════════════════════════════════════════════════════════


class TestCompleteErrors:
    """PUT mode=complete 错误路径。"""

    @pytest.mark.asyncio
    async def test_complete_version_mismatch(
        self, client: AsyncClient, registered_user: dict, auth_headers: dict, db_session: AsyncSession
    ):
        """version 不匹配 → 409。"""
        resume = await _create_draft_resume(db_session, registered_user["id"], version=3)

        with patch("services.resume_builder.process_resume", new_callable=AsyncMock), \
             patch("services.resume_builder.embedding_cache.clear_resume", new_callable=AsyncMock):
            resp = await client.put(
                f"/api/v1/resumes/{resume.id}?mode=complete",
                json={"version": 1},  # 真实 version=3
                headers=auth_headers,
            )

        assert resp.status_code == 409
        assert "版本冲突" in resp.json()["error"]["message"]

    @pytest.mark.asyncio
    async def test_complete_missing_version(
        self, client: AsyncClient, registered_user: dict, auth_headers: dict, db_session: AsyncSession
    ):
        """version 缺失 → 422。"""
        resume = await _create_draft_resume(db_session, registered_user["id"])

        with patch("services.resume_builder.process_resume", new_callable=AsyncMock), \
             patch("services.resume_builder.embedding_cache.clear_resume", new_callable=AsyncMock):
            resp = await client.put(
                f"/api/v1/resumes/{resume.id}?mode=complete",
                json={"filename": "无版本"},
                headers=auth_headers,
            )

        assert resp.status_code == 422
        assert "version" in resp.json()["error"]["message"]

    @pytest.mark.asyncio
    async def test_complete_processing_status(
        self, client: AsyncClient, registered_user: dict, auth_headers: dict, db_session: AsyncSession
    ):
        """status=processing → 409。"""
        resume = await _create_draft_resume(
            db_session, registered_user["id"], status="processing"
        )

        with patch("services.resume_builder.process_resume", new_callable=AsyncMock), \
             patch("services.resume_builder.embedding_cache.clear_resume", new_callable=AsyncMock):
            resp = await client.put(
                f"/api/v1/resumes/{resume.id}?mode=complete",
                json={"version": 1},
                headers=auth_headers,
            )

        assert resp.status_code == 409
        assert "processing" in resp.json()["error"]["message"]

    @pytest.mark.asyncio
    async def test_complete_failed_status(
        self, client: AsyncClient, registered_user: dict, auth_headers: dict, db_session: AsyncSession
    ):
        """status=failed → 409。"""
        resume = await _create_draft_resume(
            db_session, registered_user["id"], status="failed"
        )

        with patch("services.resume_builder.process_resume", new_callable=AsyncMock), \
             patch("services.resume_builder.embedding_cache.clear_resume", new_callable=AsyncMock):
            resp = await client.put(
                f"/api/v1/resumes/{resume.id}?mode=complete",
                json={"version": 1},
                headers=auth_headers,
            )

        assert resp.status_code == 409
        assert "failed" in resp.json()["error"]["message"]

    @pytest.mark.asyncio
    async def test_complete_not_owner(
        self, client: AsyncClient, registered_user: dict, auth_headers: dict, db_session: AsyncSession
    ):
        """非本人简历 → 404。"""
        other = await _create_other_user(db_session)
        resume = await _create_draft_resume(db_session, other.id)

        with patch("services.resume_builder.process_resume", new_callable=AsyncMock), \
             patch("services.resume_builder.embedding_cache.clear_resume", new_callable=AsyncMock):
            resp = await client.put(
                f"/api/v1/resumes/{resume.id}?mode=complete",
                json={"version": 1},
                headers=auth_headers,
            )

        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_complete_not_found(
        self, client: AsyncClient, auth_headers: dict
    ):
        """简历不存在 → 404。"""
        with patch("services.resume_builder.process_resume", new_callable=AsyncMock), \
             patch("services.resume_builder.embedding_cache.clear_resume", new_callable=AsyncMock):
            resp = await client.put(
                "/api/v1/resumes/99999?mode=complete",
                json={"version": 1},
                headers=auth_headers,
            )

        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_complete_chroma_failure(
        self, client: AsyncClient, registered_user: dict, auth_headers: dict, db_session: AsyncSession
    ):
        """process_resume 抛异常 → 500。"""
        resume, _ = await _create_draft_with_modules(
            db_session, registered_user["id"], _default_modules()
        )

        with patch("services.resume_builder.process_resume", new_callable=AsyncMock) as mock_pr, \
             patch("services.resume_builder.embedding_cache.clear_resume", new_callable=AsyncMock):
            mock_pr.side_effect = RuntimeError("Chroma 连接失败")

            resp = await client.put(
                f"/api/v1/resumes/{resume.id}?mode=complete",
                json={"version": 1},
                headers=auth_headers,
            )

        assert resp.status_code == 500
        assert "向量化重建失败" in resp.json()["error"]["message"]

    @pytest.mark.asyncio
    async def test_complete_invalid_module_content(
        self, client: AsyncClient, registered_user: dict, auth_headers: dict, db_session: AsyncSession
    ):
        """模块 content 校验失败 → 422。"""
        resume = await _create_draft_resume(db_session, registered_user["id"])

        with patch("services.resume_builder.process_resume", new_callable=AsyncMock), \
             patch("services.resume_builder.embedding_cache.clear_resume", new_callable=AsyncMock):
            resp = await client.put(
                f"/api/v1/resumes/{resume.id}?mode=complete",
                json={
                    "version": 1,
                    "modules": [
                        {
                            "module_type": "basic_info",
                            "content": {},  # name 必填，空 content 校验失败
                            "sort_order": 0,
                        }
                    ],
                },
                headers=auth_headers,
            )

        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_complete_unsupported_mode(
        self, client: AsyncClient, registered_user: dict, auth_headers: dict, db_session: AsyncSession
    ):
        """不支持的 mode → 422。"""
        resume = await _create_draft_resume(db_session, registered_user["id"])

        resp = await client.put(
            f"/api/v1/resumes/{resume.id}?mode=invalid",
            json={"version": 1},
            headers=auth_headers,
        )

        assert resp.status_code == 422


# ═══════════════════════════════════════════════════════════
# PUT mode=complete — 副作用验证
# ═══════════════════════════════════════════════════════════


class TestCompleteSideEffects:
    """PUT mode=complete 副作用验证。"""

    @pytest.mark.asyncio
    async def test_complete_triggers_chroma_rebuild(
        self, client: AsyncClient, registered_user: dict, auth_headers: dict, db_session: AsyncSession
    ):
        """complete 调用 process_resume（drop + rebuild Chroma）。"""
        resume, _ = await _create_draft_with_modules(
            db_session, registered_user["id"], _default_modules()
        )

        with patch("services.resume_builder.process_resume", new_callable=AsyncMock) as mock_pr, \
             patch("services.resume_builder.embedding_cache.clear_resume", new_callable=AsyncMock), \
             patch("services.react_agent.memory.build_l3_profile_background", new_callable=AsyncMock):
            mock_pr.return_value = 5

            await client.put(
                f"/api/v1/resumes/{resume.id}?mode=complete",
                json={"version": 1},
                headers=auth_headers,
            )

        mock_pr.assert_awaited_once()
        call_args = mock_pr.call_args
        assert call_args.args[0] == resume.id  # resume_id
        assert isinstance(call_args.args[1], str)  # parsed_text
        assert len(call_args.args[1]) > 0  # 非空文本

    @pytest.mark.asyncio
    async def test_complete_clears_embedding_cache(
        self, client: AsyncClient, registered_user: dict, auth_headers: dict, db_session: AsyncSession
    ):
        """complete 调用 embedding_cache.clear_resume。"""
        resume, _ = await _create_draft_with_modules(
            db_session, registered_user["id"], [_basic_info_module()]
        )

        with patch("services.resume_builder.process_resume", new_callable=AsyncMock) as mock_pr, \
             patch("services.resume_builder.embedding_cache.clear_resume", new_callable=AsyncMock) as mock_clear, \
             patch("services.react_agent.memory.build_l3_profile_background", new_callable=AsyncMock):
            mock_pr.return_value = 1
            await client.put(
                f"/api/v1/resumes/{resume.id}?mode=complete",
                json={"version": 1},
                headers=auth_headers,
            )

        mock_clear.assert_awaited_once_with(resume.id)

    @pytest.mark.asyncio
    async def test_complete_triggers_l3(
        self, client: AsyncClient, registered_user: dict, auth_headers: dict, db_session: AsyncSession
    ):
        """complete 后触发 L3 画像构建（BackgroundTasks）。"""
        resume, _ = await _create_draft_with_modules(
            db_session, registered_user["id"], _default_modules()
        )

        with patch("services.resume_builder.process_resume", new_callable=AsyncMock) as mock_pr, \
             patch("services.resume_builder.embedding_cache.clear_resume", new_callable=AsyncMock), \
             patch("services.react_agent.memory.build_l3_profile_background", new_callable=AsyncMock) as mock_l3:
            mock_pr.return_value = 5

            await client.put(
                f"/api/v1/resumes/{resume.id}?mode=complete",
                json={"version": 1},
                headers=auth_headers,
            )

        mock_l3.assert_awaited_once_with(
            resume_id=resume.id,
            user_id=registered_user["id"],
        )

    @pytest.mark.asyncio
    async def test_parsed_text_contains_section_headers(
        self, client: AsyncClient, registered_user: dict, auth_headers: dict, db_session: AsyncSession
    ):
        """parsed_text 包含节段标题（对齐 chunking SECTION_HEADERS）。"""
        resume, _ = await _create_draft_with_modules(
            db_session, registered_user["id"], _default_modules()
        )

        with patch("services.resume_builder.process_resume", new_callable=AsyncMock) as mock_pr, \
             patch("services.resume_builder.embedding_cache.clear_resume", new_callable=AsyncMock), \
             patch("services.react_agent.memory.build_l3_profile_background", new_callable=AsyncMock):
            mock_pr.return_value = 3

            await client.put(
                f"/api/v1/resumes/{resume.id}?mode=complete",
                json={"version": 1},
                headers=auth_headers,
            )

        # 从 mock_pr 的调用参数获取 parsed_text
        parsed_text = mock_pr.call_args.args[1]
        assert "个人简介" in parsed_text
        assert "教育背景" in parsed_text
        assert "专业技能" in parsed_text
        assert "张三" in parsed_text
        assert "广东海洋大学" in parsed_text
        assert "Python" in parsed_text

    @pytest.mark.asyncio
    async def test_complete_db_state_updated(
        self, client: AsyncClient, registered_user: dict, auth_headers: dict, db_session: AsyncSession
    ):
        """complete 后 DB 中 resume 状态正确更新。"""
        resume, _ = await _create_draft_with_modules(
            db_session, registered_user["id"], _default_modules()
        )

        with patch("services.resume_builder.process_resume", new_callable=AsyncMock) as mock_pr, \
             patch("services.resume_builder.embedding_cache.clear_resume", new_callable=AsyncMock), \
             patch("services.react_agent.memory.build_l3_profile_background", new_callable=AsyncMock):
            mock_pr.return_value = 7

            await client.put(
                f"/api/v1/resumes/{resume.id}?mode=complete",
                json={"version": 1},
                headers=auth_headers,
            )

        # 用全新 session 查询 DB，避免 db_session identity map 缓存旧对象
        from tests.conftest import AsyncSessionTest
        async with AsyncSessionTest() as fresh_session:
            result = await fresh_session.execute(
                select(Resume).where(Resume.id == resume.id)
            )
            db_resume = result.scalar_one()
            assert db_resume.status == "ready"
            assert db_resume.version == 2
            assert db_resume.chunk_count == 7
            assert len(db_resume.parsed_text) > 0


# ═══════════════════════════════════════════════════════════
# draft 模式向后兼容
# ═══════════════════════════════════════════════════════════


class TestDraftBackwardCompat:
    """验证 draft 模式在新 BuilderUpdateRequest body 下仍正常工作。"""

    @pytest.mark.asyncio
    async def test_draft_ignores_version(
        self, client: AsyncClient, registered_user: dict, auth_headers: dict, db_session: AsyncSession
    ):
        """draft 模式忽略 version 字段（不校验、不 bump）。"""
        resume = await _create_draft_resume(db_session, registered_user["id"])

        resp = await client.put(
            f"/api/v1/resumes/{resume.id}?mode=draft",
            json={"version": 999, "filename": "草稿改名"},  # version 被忽略
            headers=auth_headers,
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["filename"] == "草稿改名"
        assert data["version"] == 1  # version 不变
        assert data["status"] == "draft"

    @pytest.mark.asyncio
    async def test_draft_without_version(
        self, client: AsyncClient, registered_user: dict, auth_headers: dict, db_session: AsyncSession
    ):
        """draft 模式不带 version 仍正常工作。"""
        resume = await _create_draft_resume(db_session, registered_user["id"])

        resp = await client.put(
            f"/api/v1/resumes/{resume.id}?mode=draft",
            json={"filename": "无版本草稿"},
            headers=auth_headers,
        )

        assert resp.status_code == 200
        assert resp.json()["filename"] == "无版本草稿"
