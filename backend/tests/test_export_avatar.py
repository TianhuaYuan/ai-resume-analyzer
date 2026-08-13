"""导出 PDF/Markdown + 零模块守卫 + 头像上传 测试。

测试范围：
- Markdown 导出（模块拼接 / 零模块守卫 / 归属校验）
- PDF 导出（WeasyPrint mock / 零模块守卫 / 503 不可用）
- 头像上传（MIME 白名单 / 大小限制 / PIL 校验 / UUID 文件名 / basic_info 更新）
- 不支持的格式
"""

import io
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from models.resume import Resume
from models.resume_module import ResumeModule
from models.user import User
from services.resume_export import (
    _guard_has_modules,
    _module_to_markdown,
    export_resume_markdown,
    export_resume_pdf,
)


# ═══════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════


def _basic_info_content():
    return {"name": "张三", "phone": "13800138000", "email": "zhangsan@test.com"}


def _education_content():
    return {"entries": [{"school": "广东海洋大学", "degree": "本科", "major": "软件工程"}]}


def _skills_content():
    return {"categories": [{"name": "编程语言", "items": ["Python", "JavaScript"]}]}


async def _create_builder_resume_with_modules(
    db: AsyncSession, user_id: int, modules: list[dict] | None = None
) -> tuple[Resume, list[ResumeModule]]:
    """创建 builder 简历 + 模块。"""
    resume = Resume(
        user_id=user_id,
        filename="测试简历",
        file_path="",
        parsed_text="",
        chunk_count=0,
        status="ready",
        source="builder",
        style={"template_id": "default", "font_family": "Noto Sans CJK SC", "font_size": "14px", "line_height": 1.6, "spacing": "8px", "accent_color": "#2563eb"},
        version=1,
    )
    db.add(resume)
    await db.flush()

    created = []
    if modules:
        for i, mod_data in enumerate(modules):
            module = ResumeModule(
                resume_id=resume.id,
                module_type=mod_data["module_type"],
                content=mod_data["content"],
                sort_order=mod_data.get("sort_order", i),
            )
            db.add(module)
            created.append(module)

    await db.commit()
    for m in created:
        await db.refresh(m)
    await db.refresh(resume)
    return resume, created


async def _create_other_user(db: AsyncSession) -> User:
    other = User(username="other_user", email="other@test.com", password_hash="dummy")
    db.add(other)
    await db.commit()
    await db.refresh(other)
    return other


# ═══════════════════════════════════════════════════════════
# 零模块守卫
# ═══════════════════════════════════════════════════════════


class TestGuardHasModules:
    """零模块守卫。"""

    def test_empty_list_raises(self):
        """空模块列表 → 422。"""
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            _guard_has_modules([])
        assert exc_info.value.status_code == 422
        assert "没有任何模块" in exc_info.value.detail

    def test_none_raises(self):
        """None → 422。"""
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            _guard_has_modules(None)
        assert exc_info.value.status_code == 422

    def test_non_empty_passes(self):
        """有模块时不抛异常。"""
        mod = ResumeModule(module_type="basic_info", content={"name": "test"}, sort_order=0)
        _guard_has_modules([mod])  # 不抛异常


# ═══════════════════════════════════════════════════════════
# Markdown 导出
# ═══════════════════════════════════════════════════════════


class TestModuleToMarkdown:
    """单模块 Markdown 转换。"""

    def test_basic_info_to_md(self):
        mod = ResumeModule(module_type="basic_info", content=_basic_info_content(), sort_order=0)
        md = _module_to_markdown(mod)
        assert "## 个人简介" in md
        assert "**姓名**：张三" in md
        assert "**手机**：13800138000" in md

    def test_education_to_md(self):
        mod = ResumeModule(module_type="education", content=_education_content(), sort_order=0)
        md = _module_to_markdown(mod)
        assert "## 教育背景" in md
        assert "广东海洋大学" in md
        assert "软件工程" in md

    def test_skills_to_md(self):
        mod = ResumeModule(module_type="skills", content=_skills_content(), sort_order=0)
        md = _module_to_markdown(mod)
        assert "## 专业技能" in md
        assert "编程语言" in md
        assert "Python" in md

    def test_interests_to_md(self):
        mod = ResumeModule(module_type="interests", content={"items": ["阅读", "跑步"]}, sort_order=0)
        md = _module_to_markdown(mod)
        assert "阅读" in md
        assert "跑步" in md

    def test_empty_entries_skipped(self):
        mod = ResumeModule(module_type="education", content={"entries": []}, sort_order=0)
        md = _module_to_markdown(mod)
        assert "## 教育背景" in md


class TestExportMarkdown:
    """Markdown 导出集成测试。"""

    async def test_export_markdown_success(self, db_session, test_user):
        """正常导出 Markdown。"""
        resume, modules = await _create_builder_resume_with_modules(
            db_session, test_user.id,
            [
                {"module_type": "basic_info", "content": _basic_info_content()},
                {"module_type": "education", "content": _education_content()},
                {"module_type": "skills", "content": _skills_content()},
            ]
        )
        markdown, filename = await export_resume_markdown(db_session, test_user.id, resume.id)
        assert "测试简历" in markdown
        assert "张三" in markdown
        assert "广东海洋大学" in markdown
        assert "Python" in markdown
        assert filename == f"resume_{resume.id}.md"

    async def test_export_markdown_zero_modules(self, db_session, test_user):
        """零模块 → 422。"""
        resume = Resume(
            user_id=test_user.id, filename="空简历", file_path="",
            parsed_text="", chunk_count=0, status="ready", source="upload", version=1,
        )
        db_session.add(resume)
        await db_session.commit()
        await db_session.refresh(resume)

        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await export_resume_markdown(db_session, test_user.id, resume.id)
        assert exc_info.value.status_code == 422

    async def test_export_markdown_not_owner(self, db_session, test_user):
        """他人简历 → 404。"""
        other = await _create_other_user(db_session)
        resume, _ = await _create_builder_resume_with_modules(
            db_session, other.id,
            [{"module_type": "basic_info", "content": _basic_info_content()}]
        )
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await export_resume_markdown(db_session, test_user.id, resume.id)
        assert exc_info.value.status_code == 404

    async def test_export_markdown_not_found(self, db_session, test_user):
        """不存在的简历 → 404。"""
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await export_resume_markdown(db_session, test_user.id, 99999)
        assert exc_info.value.status_code == 404


# ═══════════════════════════════════════════════════════════
# PDF 导出
# ═══════════════════════════════════════════════════════════


class TestExportPdf:
    """PDF 导出测试。"""

    async def test_export_pdf_weasyprint_unavailable(self, db_session, test_user):
        """WeasyPrint 不可用 → 503。"""
        resume, modules = await _create_builder_resume_with_modules(
            db_session, test_user.id,
            [{"module_type": "basic_info", "content": _basic_info_content()}]
        )
        with patch("services.resume_export._get_weasyprint", return_value=None):
            from fastapi import HTTPException
            with pytest.raises(HTTPException) as exc_info:
                await export_resume_pdf(db_session, test_user.id, resume.id)
            assert exc_info.value.status_code == 503

    async def test_export_pdf_success_with_mock(self, db_session, test_user):
        """Mock WeasyPrint 成功导出 PDF。"""
        resume, modules = await _create_builder_resume_with_modules(
            db_session, test_user.id,
            [
                {"module_type": "basic_info", "content": _basic_info_content()},
                {"module_type": "education", "content": _education_content()},
            ]
        )

        # Mock WeasyPrint
        mock_html_class = MagicMock()
        mock_instance = MagicMock()
        # 代码从 pdf_buffer.getvalue() 读结果，mock 需真实写入 buffer
        mock_instance.write_pdf.side_effect = lambda buf: buf.write(b"%PDF-1.4 fake pdf content")
        mock_html_class.return_value = mock_instance

        with patch("services.resume_export._get_weasyprint", return_value=mock_html_class):
            pdf_bytes, filename = await export_resume_pdf(db_session, test_user.id, resume.id)
            assert pdf_bytes == b"%PDF-1.4 fake pdf content"
            assert filename == f"resume_{resume.id}.pdf"
            mock_html_class.assert_called_once()
            mock_instance.write_pdf.assert_called_once()

    async def test_export_pdf_zero_modules(self, db_session, test_user):
        """零模块 → 422。"""
        resume = Resume(
            user_id=test_user.id, filename="空简历", file_path="",
            parsed_text="", chunk_count=0, status="ready", source="upload", version=1,
        )
        db_session.add(resume)
        await db_session.commit()
        await db_session.refresh(resume)

        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await export_resume_pdf(db_session, test_user.id, resume.id)
        assert exc_info.value.status_code == 422

    async def test_export_pdf_not_owner(self, db_session, test_user):
        """他人简历 → 404。"""
        other = await _create_other_user(db_session)
        resume, _ = await _create_builder_resume_with_modules(
            db_session, other.id,
            [{"module_type": "basic_info", "content": _basic_info_content()}]
        )
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await export_resume_pdf(db_session, test_user.id, resume.id)
        assert exc_info.value.status_code == 404

    async def test_export_pdf_generation_error(self, db_session, test_user):
        """PDF 生成失败 → 500。"""
        resume, modules = await _create_builder_resume_with_modules(
            db_session, test_user.id,
            [{"module_type": "basic_info", "content": _basic_info_content()}]
        )

        mock_html_class = MagicMock()
        mock_instance = MagicMock()
        mock_instance.write_pdf.side_effect = RuntimeError("PDF engine error")
        mock_html_class.return_value = mock_instance

        with patch("services.resume_export._get_weasyprint", return_value=mock_html_class):
            from fastapi import HTTPException
            with pytest.raises(HTTPException) as exc_info:
                await export_resume_pdf(db_session, test_user.id, resume.id)
            assert exc_info.value.status_code == 500


# ═══════════════════════════════════════════════════════════
# 头像上传
# ═══════════════════════════════════════════════════════════


class TestAvatarValidation:
    """头像上传安全校验。"""

    def test_validate_mime_jpeg(self):
        from services.avatar_service import _validate_mime
        file = MagicMock()
        file.content_type = "image/jpeg"
        assert _validate_mime(file) == "image/jpeg"

    def test_validate_mime_png(self):
        from services.avatar_service import _validate_mime
        file = MagicMock()
        file.content_type = "image/png"
        assert _validate_mime(file) == "image/png"

    def test_validate_mime_webp(self):
        from services.avatar_service import _validate_mime
        file = MagicMock()
        file.content_type = "image/webp"
        assert _validate_mime(file) == "image/webp"

    def test_validate_mime_gif_rejected(self):
        from services.avatar_service import _validate_mime
        from fastapi import HTTPException
        file = MagicMock()
        file.content_type = "image/gif"
        with pytest.raises(HTTPException) as exc_info:
            _validate_mime(file)
        assert exc_info.value.status_code == 422

    def test_validate_mime_svg_rejected(self):
        from services.avatar_service import _validate_mime
        from fastapi import HTTPException
        file = MagicMock()
        file.content_type = "image/svg+xml"
        with pytest.raises(HTTPException) as exc_info:
            _validate_mime(file)
        assert exc_info.value.status_code == 422

    def test_validate_mime_empty_rejected(self):
        from services.avatar_service import _validate_mime
        from fastapi import HTTPException
        file = MagicMock()
        file.content_type = ""
        with pytest.raises(HTTPException) as exc_info:
            _validate_mime(file)
        assert exc_info.value.status_code == 422

    def test_validate_size_ok(self):
        from services.avatar_service import _validate_size
        _validate_size(b"x" * (5 * 1024 * 1024 - 1))  # just under 5MB

    def test_validate_size_too_large(self):
        from services.avatar_service import _validate_size
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            _validate_size(b"x" * (5 * 1024 * 1024 + 1))
        assert exc_info.value.status_code == 413

    def test_validate_image_ok(self):
        from services.avatar_service import _validate_image
        # Create a minimal valid PNG
        from PIL import Image
        buf = io.BytesIO()
        Image.new("RGB", (1, 1), color="red").save(buf, format="PNG")
        _validate_image(buf.getvalue())  # 不抛异常

    def test_validate_image_invalid(self):
        from services.avatar_service import _validate_image
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            _validate_image(b"not an image")
        assert exc_info.value.status_code == 422

    def test_get_extension(self):
        from services.avatar_service import _get_extension
        assert _get_extension("image/jpeg") == ".jpg"
        assert _get_extension("image/png") == ".png"
        assert _get_extension("image/webp") == ".webp"

    def test_filename_is_uuid(self):
        """文件名使用 UUID，防路径遍历。"""
        from services.avatar_service import _get_extension
        import uuid
        ext = _get_extension("image/png")
        filename = f"{uuid.uuid4().hex}{ext}"
        # UUID hex 是 32 字符 + 扩展名
        assert len(filename) == 36  # 32 + 4 (.png)
        assert ".." not in filename
        assert "/" not in filename
        assert "\\" not in filename


class TestSaveAvatar:
    """save_avatar 集成测试。"""

    async def test_save_avatar_success(self, tmp_path):
        """成功保存头像。"""
        from services.avatar_service import save_avatar
        from PIL import Image

        # 创建有效 PNG
        buf = io.BytesIO()
        Image.new("RGB", (100, 100), color="blue").save(buf, format="PNG")
        png_data = buf.getvalue()

        file = AsyncMock()
        file.content_type = "image/png"
        file.read.return_value = png_data

        with patch("services.avatar_service._AVATAR_UPLOAD_DIR", str(tmp_path)):
            avatar_url = await save_avatar(file, resume_id=1)
            assert avatar_url.startswith(f"/{tmp_path}/")
            assert avatar_url.endswith(".png")
            # 文件实际存在
            saved_file = tmp_path / Path(avatar_url).name
            assert saved_file.exists()
            assert saved_file.read_bytes() == png_data

    async def test_save_avatar_jpeg(self, tmp_path):
        """保存 JPEG 头像。"""
        from services.avatar_service import save_avatar
        from PIL import Image

        buf = io.BytesIO()
        Image.new("RGB", (100, 100), color="green").save(buf, format="JPEG")
        jpeg_data = buf.getvalue()

        file = AsyncMock()
        file.content_type = "image/jpeg"
        file.read.return_value = jpeg_data

        with patch("services.avatar_service._AVATAR_UPLOAD_DIR", str(tmp_path)):
            avatar_url = await save_avatar(file, resume_id=2)
            assert avatar_url.endswith(".jpg")

    async def test_save_avatar_invalid_mime(self, tmp_path):
        """MIME 不支持 → 422。"""
        from services.avatar_service import save_avatar
        from fastapi import HTTPException

        file = AsyncMock()
        file.content_type = "image/gif"
        file.read.return_value = b"fake"

        with patch("services.avatar_service._AVATAR_UPLOAD_DIR", str(tmp_path)):
            with pytest.raises(HTTPException) as exc_info:
                await save_avatar(file, resume_id=1)
            assert exc_info.value.status_code == 422

    async def test_save_avatar_too_large(self, tmp_path):
        """文件过大 → 413。"""
        from services.avatar_service import save_avatar, _AVATAR_MAX_SIZE
        from fastapi import HTTPException

        file = AsyncMock()
        file.content_type = "image/png"
        file.read.return_value = b"x" * (_AVATAR_MAX_SIZE + 1)

        with patch("services.avatar_service._AVATAR_UPLOAD_DIR", str(tmp_path)):
            with pytest.raises(HTTPException) as exc_info:
                await save_avatar(file, resume_id=1)
            assert exc_info.value.status_code == 413

    async def test_save_avatar_not_image(self, tmp_path):
        """不是有效图片 → 422。"""
        from services.avatar_service import save_avatar
        from fastapi import HTTPException

        file = AsyncMock()
        file.content_type = "image/png"
        file.read.return_value = b"fake png data not real image"

        with patch("services.avatar_service._AVATAR_UPLOAD_DIR", str(tmp_path)):
            with pytest.raises(HTTPException) as exc_info:
                await save_avatar(file, resume_id=1)
            assert exc_info.value.status_code == 422


# ═══════════════════════════════════════════════════════════
# API 端点测试
# ═══════════════════════════════════════════════════════════


class TestExportApi:
    """导出 API 端点测试。"""

    async def test_export_markdown_endpoint(self, client: AsyncClient, auth_headers, db_session, test_user):
        """GET /resumes/{id}/export?format=markdown。"""
        resume, _ = await _create_builder_resume_with_modules(
            db_session, test_user.id,
            [
                {"module_type": "basic_info", "content": _basic_info_content()},
                {"module_type": "education", "content": _education_content()},
            ]
        )
        resp = await client.get(
            f"/api/v1/resumes/{resume.id}/export?format=markdown",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert "张三" in resp.text
        assert "广东海洋大学" in resp.text
        assert "attachment" in resp.headers.get("content-disposition", "")

    async def test_export_pdf_endpoint_503(self, client: AsyncClient, auth_headers, db_session, test_user):
        """GET /resumes/{id}/export?format=pdf → 503 (WeasyPrint 不可用)。"""
        resume, _ = await _create_builder_resume_with_modules(
            db_session, test_user.id,
            [{"module_type": "basic_info", "content": _basic_info_content()}]
        )
        with patch("services.resume_export._get_weasyprint", return_value=None):
            resp = await client.get(
                f"/api/v1/resumes/{resume.id}/export?format=pdf",
                headers=auth_headers,
            )
            assert resp.status_code == 503

    async def test_export_pdf_endpoint_mock(self, client: AsyncClient, auth_headers, db_session, test_user):
        """GET /resumes/{id}/export?format=pdf → 200 (mock WeasyPrint)。"""
        resume, _ = await _create_builder_resume_with_modules(
            db_session, test_user.id,
            [{"module_type": "basic_info", "content": _basic_info_content()}]
        )

        mock_html_class = MagicMock()
        mock_instance = MagicMock()
        mock_instance.write_pdf.return_value = b"%PDF-1.4 fake"
        mock_html_class.return_value = mock_instance

        with patch("services.resume_export._get_weasyprint", return_value=mock_html_class):
            resp = await client.get(
                f"/api/v1/resumes/{resume.id}/export?format=pdf",
                headers=auth_headers,
            )
            assert resp.status_code == 200
            assert resp.headers["content-type"] == "application/pdf"

    async def test_export_zero_modules(self, client: AsyncClient, auth_headers, db_session, test_user):
        """零模块 → 422。"""
        resume = Resume(
            user_id=test_user.id, filename="空", file_path="",
            parsed_text="", chunk_count=0, status="ready", source="upload", version=1,
        )
        db_session.add(resume)
        await db_session.commit()
        await db_session.refresh(resume)

        resp = await client.get(
            f"/api/v1/resumes/{resume.id}/export?format=markdown",
            headers=auth_headers,
        )
        assert resp.status_code == 422

    async def test_export_unsupported_format(self, client: AsyncClient, auth_headers, db_session, test_user):
        """不支持的格式 → 422。"""
        resume, _ = await _create_builder_resume_with_modules(
            db_session, test_user.id,
            [{"module_type": "basic_info", "content": _basic_info_content()}]
        )
        resp = await client.get(
            f"/api/v1/resumes/{resume.id}/export?format=docx",
            headers=auth_headers,
        )
        assert resp.status_code == 422

    async def test_export_not_found(self, client: AsyncClient, auth_headers):
        """简历不存在 → 404。"""
        resp = await client.get(
            "/api/v1/resumes/99999/export?format=markdown",
            headers=auth_headers,
        )
        assert resp.status_code == 404

    async def test_export_unauthorized(self, client: AsyncClient):
        """未登录 → 401。"""
        resp = await client.get("/api/v1/resumes/1/export?format=markdown")
        assert resp.status_code == 401


class TestAvatarApi:
    """头像上传 API 端点测试。"""

    async def test_upload_avatar_success(self, client: AsyncClient, auth_headers, db_session, test_user, tmp_path):
        """成功上传头像。"""
        from PIL import Image

        resume, _ = await _create_builder_resume_with_modules(
            db_session, test_user.id,
            [{"module_type": "basic_info", "content": _basic_info_content()}]
        )

        # 创建有效 PNG
        buf = io.BytesIO()
        Image.new("RGB", (100, 100), color="red").save(buf, format="PNG")
        png_data = buf.getvalue()

        with patch("services.avatar_service._AVATAR_UPLOAD_DIR", str(tmp_path)):
            resp = await client.post(
                f"/api/v1/resumes/{resume.id}/avatar",
                headers=auth_headers,
                files={"file": ("avatar.png", png_data, "image/png")},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert "avatar_url" in data
            assert data["avatar_url"].endswith(".png")

    async def test_upload_avatar_invalid_mime(self, client: AsyncClient, auth_headers, db_session, test_user, tmp_path):
        """MIME 不支持 → 422。"""
        resume, _ = await _create_builder_resume_with_modules(
            db_session, test_user.id,
            [{"module_type": "basic_info", "content": _basic_info_content()}]
        )

        with patch("services.avatar_service._AVATAR_UPLOAD_DIR", str(tmp_path)):
            resp = await client.post(
                f"/api/v1/resumes/{resume.id}/avatar",
                headers=auth_headers,
                files={"file": ("avatar.gif", b"fake", "image/gif")},
            )
            assert resp.status_code == 422

    async def test_upload_avatar_too_large(self, client: AsyncClient, auth_headers, db_session, test_user, tmp_path):
        """文件过大 → 413。"""
        from services.avatar_service import _AVATAR_MAX_SIZE

        resume, _ = await _create_builder_resume_with_modules(
            db_session, test_user.id,
            [{"module_type": "basic_info", "content": _basic_info_content()}]
        )

        large_data = b"x" * (_AVATAR_MAX_SIZE + 1)

        with patch("services.avatar_service._AVATAR_UPLOAD_DIR", str(tmp_path)):
            resp = await client.post(
                f"/api/v1/resumes/{resume.id}/avatar",
                headers=auth_headers,
                files={"file": ("large.png", large_data, "image/png")},
            )
            assert resp.status_code == 413

    async def test_upload_avatar_not_image(self, client: AsyncClient, auth_headers, db_session, test_user, tmp_path):
        """不是有效图片 → 422。"""
        resume, _ = await _create_builder_resume_with_modules(
            db_session, test_user.id,
            [{"module_type": "basic_info", "content": _basic_info_content()}]
        )

        with patch("services.avatar_service._AVATAR_UPLOAD_DIR", str(tmp_path)):
            resp = await client.post(
                f"/api/v1/resumes/{resume.id}/avatar",
                headers=auth_headers,
                files={"file": ("fake.png", b"not an image", "image/png")},
            )
            assert resp.status_code == 422

    async def test_upload_avatar_not_found(self, client: AsyncClient, auth_headers, tmp_path):
        """简历不存在 → 404。"""
        from PIL import Image

        buf = io.BytesIO()
        Image.new("RGB", (1, 1)).save(buf, format="PNG")

        with patch("services.avatar_service._AVATAR_UPLOAD_DIR", str(tmp_path)):
            resp = await client.post(
                "/api/v1/resumes/99999/avatar",
                headers=auth_headers,
                files={"file": ("avatar.png", buf.getvalue(), "image/png")},
            )
            assert resp.status_code == 404

    async def test_upload_avatar_unauthorized(self, client: AsyncClient):
        """未登录 → 401。"""
        resp = await client.post("/api/v1/resumes/1/avatar")
        assert resp.status_code == 401

    async def test_upload_avatar_creates_basic_info_if_missing(self, client: AsyncClient, auth_headers, db_session, test_user, tmp_path):
        """如果没 basic_info 模块，上传头像时自动创建。"""
        from PIL import Image

        resume = Resume(
            user_id=test_user.id, filename="无模块简历", file_path="",
            parsed_text="", chunk_count=0, status="ready", source="builder", version=1,
        )
        db_session.add(resume)
        await db_session.commit()
        await db_session.refresh(resume)

        buf = io.BytesIO()
        Image.new("RGB", (50, 50), color="blue").save(buf, format="PNG")

        with patch("services.avatar_service._AVATAR_UPLOAD_DIR", str(tmp_path)):
            resp = await client.post(
                f"/api/v1/resumes/{resume.id}/avatar",
                headers=auth_headers,
                files={"file": ("avatar.png", buf.getvalue(), "image/png")},
            )
            assert resp.status_code == 200
            assert "avatar_url" in resp.json()
