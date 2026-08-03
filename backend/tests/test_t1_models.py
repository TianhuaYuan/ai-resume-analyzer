"""T1: alembic 004 全量迁移 — 模型层测试。

测试范围：
- 改表：resumes 加 source/style/version/expires_at；users 加 password_changed_at；
  qa_history 加 status；resumes.status 兼容 draft
- 新表：resume_modules / audit_log / qa_feedback / user_feedback
- 级联删除关系验证
"""

import pytest
from sqlalchemy import select

from models import User, Resume, QAHistory
from tests.conftest import AsyncSessionTest


# ═══════════════════════════════════════════════════════════
# RED 步骤：先导入新模型（此时不存在，导入必失败）
# ═══════════════════════════════════════════════════════════
from models.resume_module import ResumeModule
from models.audit_log import AuditLog
from models.qa_feedback import QAFeedback
from models.user_feedback import UserFeedback


# ── 改表兼容测试 ──

@pytest.mark.asyncio
async def test_resume_has_new_columns():
    """resumes 表新增 4 列可正常读写。"""
    async with AsyncSessionTest() as db_session:
        user = User(
            username="testu",
            email="test@example.com",
            password_hash="$2b$12$fake",
        )
        db_session.add(user)
        await db_session.flush()

        resume = Resume(
            user_id=user.id,
            filename="test.pdf",
            file_path="/uploads/test.pdf",
            parsed_text="some text",
            source="upload",
            style={"template_id": "default", "font_family": "sans-serif"},
            version=1,
            expires_at=None,
        )
        db_session.add(resume)
        await db_session.commit()

        result = await db_session.execute(select(Resume).where(Resume.id == resume.id))
        r = result.scalar_one()
        assert r.source == "upload"
        assert r.style == {"template_id": "default", "font_family": "sans-serif"}
        assert r.version == 1
        assert r.expires_at is None


@pytest.mark.asyncio
async def test_resume_status_accepts_draft():
    """resumes.status 可以设置为 draft。"""
    async with AsyncSessionTest() as db_session:
        user = User(
            username="draftu",
            email="draft@example.com",
            password_hash="$2b$12$fake",
        )
        db_session.add(user)
        await db_session.flush()

        resume = Resume(
            user_id=user.id,
            filename="draft.pdf",
            file_path="/uploads/draft.pdf",
            parsed_text="",
            status="draft",
            source="builder",
            version=1,
        )
        db_session.add(resume)
        await db_session.commit()

        result = await db_session.execute(select(Resume).where(Resume.id == resume.id))
        r = result.scalar_one()
        assert r.status == "draft"


@pytest.mark.asyncio
async def test_user_has_password_changed_at():
    """users 表新增 password_changed_at 列可正常读写。"""
    from datetime import datetime, timezone

    async with AsyncSessionTest() as db_session:
        user = User(
            username="pwu",
            email="pw@example.com",
            password_hash="$2b$12$fake",
            password_changed_at=datetime(2026, 7, 31, tzinfo=timezone.utc),
        )
        db_session.add(user)
        await db_session.commit()

        result = await db_session.execute(select(User).where(User.id == user.id))
        u = result.scalar_one()
        assert u.password_changed_at is not None


@pytest.mark.asyncio
async def test_qa_history_has_status():
    """qa_history 表新增 status 列可正常读写。"""
    async with AsyncSessionTest() as db_session:
        user = User(
            username="qau",
            email="qa@example.com",
            password_hash="$2b$12$fake",
        )
        db_session.add(user)
        await db_session.flush()

        resume = Resume(
            user_id=user.id,
            filename="qa.pdf",
            file_path="/uploads/qa.pdf",
            parsed_text="text",
        )
        db_session.add(resume)
        await db_session.flush()

        qa = QAHistory(
            user_id=user.id,
            resume_id=resume.id,
            question="test",
            answer="test",
            status="complete",
        )
        db_session.add(qa)
        await db_session.commit()

        result = await db_session.execute(select(QAHistory).where(QAHistory.id == qa.id))
        q = result.scalar_one()
        assert q.status == "complete"


# ── 新表 CRUD 测试 ──

@pytest.mark.asyncio
async def test_resume_module_crud():
    """resume_modules 表 CRUD + 唯一约束。"""
    async with AsyncSessionTest() as db_session:
        user = User(
            username="rmu",
            email="rm@example.com",
            password_hash="$2b$12$fake",
        )
        db_session.add(user)
        await db_session.flush()

        resume = Resume(
            user_id=user.id,
            filename="rm.pdf",
            file_path="/uploads/rm.pdf",
            parsed_text="text",
        )
        db_session.add(resume)
        await db_session.flush()

        mod = ResumeModule(
            resume_id=resume.id,
            module_type="basic_info",
            content={"name": "张三", "phone": "13800138000"},
            sort_order=0,
        )
        db_session.add(mod)
        await db_session.commit()

        result = await db_session.execute(select(ResumeModule).where(ResumeModule.id == mod.id))
        m = result.scalar_one()
        assert m.module_type == "basic_info"
        assert m.content["name"] == "张三"


@pytest.mark.asyncio
async def test_resume_module_unique_constraint():
    """同一 resume 同一 module_type 不能重复（唯一约束）。"""
    async with AsyncSessionTest() as db_session:
        user = User(
            username="rmuq",
            email="rmu@example.com",
            password_hash="$2b$12$fake",
        )
        db_session.add(user)
        await db_session.flush()

        resume = Resume(
            user_id=user.id,
            filename="rmu.pdf",
            file_path="/uploads/rmu.pdf",
            parsed_text="text",
        )
        db_session.add(resume)
        await db_session.flush()

        mod1 = ResumeModule(
            resume_id=resume.id,
            module_type="basic_info",
            content={},
            sort_order=0,
        )
        db_session.add(mod1)
        await db_session.commit()

        # 违反唯一约束
        mod2 = ResumeModule(
            resume_id=resume.id,
            module_type="basic_info",
            content={},
            sort_order=1,
        )
        db_session.add(mod2)
        with pytest.raises(Exception):
            await db_session.commit()


@pytest.mark.asyncio
async def test_audit_log_crud():
    """audit_log 表 CRUD。"""
    async with AsyncSessionTest() as db_session:
        user = User(
            username="alu",
            email="al@example.com",
            password_hash="$2b$12$fake",
        )
        db_session.add(user)
        await db_session.flush()

        log = AuditLog(
            user_id=user.id,
            action="DELETE_RESUME",
            target_type="resume",
            target_id="42",
            detail={"reason": "user_request"},
            ip="127.0.0.1",
        )
        db_session.add(log)
        await db_session.commit()

        result = await db_session.execute(select(AuditLog).where(AuditLog.id == log.id))
        l = result.scalar_one()
        assert l.action == "DELETE_RESUME"
        assert l.detail["reason"] == "user_request"


@pytest.mark.asyncio
async def test_qa_feedback_crud():
    """qa_feedback 表 CRUD。"""
    async with AsyncSessionTest() as db_session:
        user = User(
            username="qfu",
            email="qf@example.com",
            password_hash="$2b$12$fake",
        )
        db_session.add(user)
        await db_session.flush()

        resume = Resume(
            user_id=user.id,
            filename="qf.pdf",
            file_path="/uploads/qf.pdf",
            parsed_text="text",
        )
        db_session.add(resume)
        await db_session.flush()

        qa = QAHistory(
            user_id=user.id,
            resume_id=resume.id,
            question="test",
            answer="test",
        )
        db_session.add(qa)
        await db_session.flush()

        fb = QAFeedback(
            qa_id=qa.id,
            rating=1,
        )
        db_session.add(fb)
        await db_session.commit()

        result = await db_session.execute(select(QAFeedback).where(QAFeedback.id == fb.id))
        f = result.scalar_one()
        assert f.rating == 1


@pytest.mark.asyncio
async def test_user_feedback_crud():
    """user_feedback 表 CRUD。"""
    async with AsyncSessionTest() as db_session:
        user = User(
            username="ufu",
            email="uf@example.com",
            password_hash="$2b$12$fake",
        )
        db_session.add(user)
        await db_session.flush()

        fb = UserFeedback(
            user_id=user.id,
            content="很好用的产品",
            type="suggestion",
            status="open",
        )
        db_session.add(fb)
        await db_session.commit()

        result = await db_session.execute(select(UserFeedback).where(UserFeedback.id == fb.id))
        f = result.scalar_one()
        assert f.content == "很好用的产品"
        assert f.status == "open"


# ── 级联删除测试 ──

@pytest.mark.asyncio
async def test_resume_cascade_deletes_modules():
    """删除 resume 时 resume_modules CASCADE 删除。"""
    async with AsyncSessionTest() as db_session:
        user = User(
            username="ccu",
            email="cc@example.com",
            password_hash="$2b$12$fake",
        )
        db_session.add(user)
        await db_session.flush()

        resume = Resume(
            user_id=user.id,
            filename="cc.pdf",
            file_path="/uploads/cc.pdf",
            parsed_text="text",
        )
        db_session.add(resume)
        await db_session.flush()

        mod = ResumeModule(
            resume_id=resume.id,
            module_type="skills",
            content={"items": ["Python"]},
            sort_order=0,
        )
        db_session.add(mod)
        await db_session.commit()

        # 删除 resume
        await db_session.delete(resume)
        await db_session.commit()

        # resume_modules 应被级联删除
        result = await db_session.execute(select(ResumeModule).where(ResumeModule.id == mod.id))
        assert result.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_user_cascade_deletes_all():
    """删除 user 时 resumes / qa_history CASCADE 删除。"""
    async with AsyncSessionTest() as db_session:
        user = User(
            username="cau",
            email="ca@example.com",
            password_hash="$2b$12$fake",
        )
        db_session.add(user)
        await db_session.flush()

        resume = Resume(
            user_id=user.id,
            filename="ca.pdf",
            file_path="/uploads/ca.pdf",
            parsed_text="text",
        )
        db_session.add(resume)
        await db_session.flush()

        qa = QAHistory(
            user_id=user.id,
            resume_id=resume.id,
            question="q",
            answer="a",
        )
        db_session.add(qa)
        await db_session.commit()

        # 删除 user
        await db_session.delete(user)
        await db_session.commit()

        # resumes 应被级联删除
        r = await db_session.execute(select(Resume).where(Resume.id == resume.id))
        assert r.scalar_one_or_none() is None

        # qa_history 应被级联删除
        q = await db_session.execute(select(QAHistory).where(QAHistory.id == qa.id))
        assert q.scalar_one_or_none() is None


# ── 回填兼容测试 ──

@pytest.mark.asyncio
async def test_existing_resume_backfill_defaults():
    """已有 resume 行不写新列时，默认值正确。"""
    async with AsyncSessionTest() as db_session:
        user = User(
            username="bfu",
            email="bf@example.com",
            password_hash="$2b$12$fake",
        )
        db_session.add(user)
        await db_session.flush()

        # 不写新列（模拟已有行）
        resume = Resume(
            user_id=user.id,
            filename="bf.pdf",
            file_path="/uploads/bf.pdf",
            parsed_text="text",
        )
        db_session.add(resume)
        await db_session.commit()

        result = await db_session.execute(select(Resume).where(Resume.id == resume.id))
        r = result.scalar_one()
        assert r.source == "upload"  # 默认回填
        assert r.version == 1        # 默认回填
        assert r.style is None
        assert r.expires_at is None
