"""T9: 反馈闭环后端（/qa/{id}/feedback + /feedback 意见箱）。

测试范围：
- POST /api/v1/qa/{qa_id}/feedback  赞/踩存 qa_feedback 表
- POST /api/v1/feedback            用户提交意见箱
- GET  /api/v1/feedback            管理员分页查看意见箱
- 归属校验 + 参数校验 + 权限校验
"""

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.qa_feedback import QAFeedback
from models.qa_history import QAHistory
from models.resume import Resume
from models.user_feedback import UserFeedback
from services.qa_service import save_qa


# ═══════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════


async def _create_resume(db: AsyncSession, user_id: int) -> Resume:
    """为测试创建一份简历。"""
    resume = Resume(
        user_id=user_id,
        filename="test.pdf",
        file_path="/tmp/test.pdf",
        parsed_text="test",
    )
    db.add(resume)
    await db.commit()
    await db.refresh(resume)
    return resume


async def _create_qa_record(db: AsyncSession, user_id: int) -> QAHistory:
    """为测试创建一条问答记录。"""
    resume = await _create_resume(db, user_id)
    return await save_qa(
        db,
        user_id=user_id,
        resume_id=resume.id,
        question="测试问题",
        answer="测试答案",
        sources=[],
    )


# ═══════════════════════════════════════════════════════════
# QA 反馈（点赞/踩）
# ═══════════════════════════════════════════════════════════


class TestQAFeedback:
    """POST /api/v1/qa/{qa_id}/feedback"""

    @pytest.mark.asyncio
    async def test_submit_positive_feedback(
        self, client: AsyncClient, registered_user: dict, auth_headers: dict, db_session: AsyncSession
    ):
        """有效 positive 反馈应写入 qa_feedback 表，rating=1。"""
        qa = await _create_qa_record(db_session, registered_user["id"])

        resp = await client.post(
            f"/api/v1/qa/{qa.id}/feedback",
            json={"rating": "positive"},
            headers=auth_headers,
        )
        assert resp.status_code == 204

        result = await db_session.execute(select(QAFeedback).where(QAFeedback.qa_id == qa.id))
        fb = result.scalar_one_or_none()
        assert fb is not None
        assert fb.rating == 1

    @pytest.mark.asyncio
    async def test_submit_negative_feedback(
        self, client: AsyncClient, registered_user: dict, auth_headers: dict, db_session: AsyncSession
    ):
        """有效 negative 反馈应写入 qa_feedback 表，rating=-1。"""
        qa = await _create_qa_record(db_session, registered_user["id"])

        resp = await client.post(
            f"/api/v1/qa/{qa.id}/feedback",
            json={"rating": "negative"},
            headers=auth_headers,
        )
        assert resp.status_code == 204

        result = await db_session.execute(select(QAFeedback).where(QAFeedback.qa_id == qa.id))
        fb = result.scalar_one_or_none()
        assert fb is not None
        assert fb.rating == -1

    @pytest.mark.asyncio
    async def test_submit_feedback_invalid_rating(
        self, client: AsyncClient, registered_user: dict, auth_headers: dict, db_session: AsyncSession
    ):
        """rating 不是 positive/negative 时应返回 422。"""
        qa = await _create_qa_record(db_session, registered_user["id"])

        resp = await client.post(
            f"/api/v1/qa/{qa.id}/feedback",
            json={"rating": "whatever"},
            headers=auth_headers,
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_submit_feedback_qa_not_found(
        self, client: AsyncClient, registered_user: dict, auth_headers: dict
    ):
        """qa_id 不存在时返回 404。"""
        resp = await client.post(
            "/api/v1/qa/99999/feedback",
            json={"rating": "positive"},
            headers=auth_headers,
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_submit_feedback_not_owner(
        self, client: AsyncClient, registered_user: dict, auth_headers: dict, db_session: AsyncSession
    ):
        """不能给别人家的 qa 打反馈，返回 403。"""
        # 注册另一个用户
        other_user_data = {
            "username": "otheruser",
            "email": "other@example.com",
            "password": "Test1234!",
            "password_confirm": "Test1234!",
        }
        await client.post("/api/v1/auth/send-code", json={"email": other_user_data["email"]})
        from services.verification_service import _in_memory_codes, _CODE_KEY_PREFIX
        code_key = f"{_CODE_KEY_PREFIX}{other_user_data['email']}"
        code_entry = _in_memory_codes.get(code_key)
        verification_code = code_entry["code"] if code_entry else "123456"
        register_data = {**other_user_data, "verification_code": verification_code}
        resp = await client.post("/api/v1/auth/register", json=register_data)
        assert resp.status_code == 201
        other_user_id = resp.json()["id"]

        # 构造一个属于 other_user 的 qa 记录
        qa = await _create_qa_record(db_session, user_id=other_user_id)

        resp = await client.post(
            f"/api/v1/qa/{qa.id}/feedback",
            json={"rating": "positive"},
            headers=auth_headers,
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_submit_feedback_duplicate_overwrites(
        self, client: AsyncClient, registered_user: dict, auth_headers: dict, db_session: AsyncSession
    ):
        """同一 qa_id 重复反馈应覆盖（或先删后插），最终只保留一条。"""
        qa = await _create_qa_record(db_session, registered_user["id"])

        await client.post(
            f"/api/v1/qa/{qa.id}/feedback",
            json={"rating": "positive"},
            headers=auth_headers,
        )
        await client.post(
            f"/api/v1/qa/{qa.id}/feedback",
            json={"rating": "negative"},
            headers=auth_headers,
        )

        result = await db_session.execute(select(QAFeedback).where(QAFeedback.qa_id == qa.id))
        rows = result.scalars().all()
        assert len(rows) == 1
        assert rows[0].rating == -1


# ═══════════════════════════════════════════════════════════
# 用户意见箱
# ═══════════════════════════════════════════════════════════


class TestUserFeedback:
    """POST /api/v1/feedback + GET /api/v1/feedback"""

    @pytest.mark.asyncio
    async def test_submit_user_feedback(
        self, client: AsyncClient, registered_user: dict, auth_headers: dict, db_session: AsyncSession
    ):
        """正常提交意见箱。"""
        resp = await client.post(
            "/api/v1/feedback",
            json={"content": "这个功能非常好用！", "type": "suggestion"},
            headers=auth_headers,
        )
        assert resp.status_code == 201

        result = await db_session.execute(
            select(UserFeedback).where(UserFeedback.user_id == registered_user["id"])
        )
        fb = result.scalar_one_or_none()
        assert fb is not None
        assert fb.content == "这个功能非常好用！"
        assert fb.type == "suggestion"
        assert fb.status == "open"

    @pytest.mark.asyncio
    async def test_submit_user_feedback_validation_empty(
        self, client: AsyncClient, registered_user: dict, auth_headers: dict
    ):
        """content 为空时应 422。"""
        resp = await client.post(
            "/api/v1/feedback",
            json={"content": "", "type": "suggestion"},
            headers=auth_headers,
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_submit_user_feedback_validation_too_long(
        self, client: AsyncClient, registered_user: dict, auth_headers: dict
    ):
        """content 超过 2000 字时应 422。"""
        resp = await client.post(
            "/api/v1/feedback",
            json={"content": "x" * 2001, "type": "suggestion"},
            headers=auth_headers,
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_get_feedback_as_admin(
        self, client: AsyncClient, registered_user: dict, auth_headers: dict, db_session: AsyncSession
    ):
        """管理员 GET /feedback 应返回列表。"""
        # 把当前用户提升为管理员
        from core.config import settings
        original = settings.ADMIN_EMAILS
        settings.ADMIN_EMAILS = [registered_user["email"]]

        # 先塞两条
        for i in range(2):
            db_session.add(
                UserFeedback(
                    user_id=registered_user["id"],
                    content=f"反馈{i}",
                    type="bug",
                )
            )
        await db_session.commit()

        resp = await client.get("/api/v1/feedback?limit=10&offset=0", headers=auth_headers)
        settings.ADMIN_EMAILS = original

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 2
        assert len(data["items"]) >= 2

    @pytest.mark.asyncio
    async def test_get_feedback_as_non_admin(
        self, client: AsyncClient, registered_user: dict, auth_headers: dict
    ):
        """非管理员 GET /feedback 应 403。"""
        resp = await client.get("/api/v1/feedback", headers=auth_headers)
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_get_feedback_pagination(
        self, client: AsyncClient, registered_user: dict, auth_headers: dict, db_session: AsyncSession
    ):
        """分页 limit/offset 生效。"""
        from core.config import settings
        original = settings.ADMIN_EMAILS
        settings.ADMIN_EMAILS = [registered_user["email"]]

        for i in range(5):
            db_session.add(
                UserFeedback(
                    user_id=registered_user["id"],
                    content=f"反馈{i}",
                    type="suggestion",
                )
            )
        await db_session.commit()

        resp = await client.get("/api/v1/feedback?limit=2&offset=0", headers=auth_headers)
        settings.ADMIN_EMAILS = original

        assert resp.status_code == 200
        data = resp.json()
        assert len(data["items"]) == 2
