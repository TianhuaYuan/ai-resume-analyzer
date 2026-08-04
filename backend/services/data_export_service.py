"""C3: 用户全量数据导出服务（信任合规——用户有权带走自己的数据）。

导出当前用户的全部私有数据（按 user_id 归属的表），返回结构化 JSON：
- 账户信息（不含密码哈希等敏感字段）
- 简历（含结构化模块）
- 问答历史
- 求职跟踪（campus_tracks）
- 知识资产（knowledge_assets）
- 意见箱反馈 + 点赞

设计：
- 只导出 user_id 归属的数据（market_assets 等公共数据不导出）
- 敏感字段（password_hash / 验证码等）一律剔除
- 时间统一 ISO 格式，前端可直接下载为 JSON
"""

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.campus_track import CampusTrack
from models.feedback_like import FeedbackLike
from models.knowledge_asset import KnowledgeAsset
from models.qa_history import QAHistory
from models.resume import Resume
from models.resume_module import ResumeModule
from models.user import User
from models.user_feedback import UserFeedback

logger = logging.getLogger(__name__)


async def export_user_data(db: AsyncSession, user_id: int) -> dict:
    """导出用户全量私有数据。

    Args:
        db: 数据库 session
        user_id: 用户 ID

    Returns:
        结构化导出数据（JSON 可序列化）
    """
    user = await db.get(User, user_id)

    # ── 账户信息（剔除敏感字段）──
    account = {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "created_at": _iso(user.created_at),
    }

    # ── 简历 + 结构化模块 ──
    resumes = (
        await db.execute(select(Resume).where(Resume.user_id == user_id))
    ).scalars().all()
    resume_ids = [r.id for r in resumes]
    modules_by_resume: dict[int, list] = {}
    if resume_ids:
        modules = (
            await db.execute(
                select(ResumeModule)
                .where(ResumeModule.resume_id.in_(resume_ids))
                .order_by(ResumeModule.resume_id, ResumeModule.sort_order)
            )
        ).scalars().all()
        for m in modules:
            modules_by_resume.setdefault(m.resume_id, []).append(
                {
                    "module_type": m.module_type,
                    "content": m.content,
                    "sort_order": m.sort_order,
                }
            )
    resume_data = [
        {
            "id": r.id,
            "filename": r.filename,
            "source": r.source,
            "status": r.status,
            "created_at": _iso(r.created_at),
            "updated_at": _iso(r.updated_at),
            "modules": modules_by_resume.get(r.id, []),
        }
        for r in resumes
    ]

    # ── 问答历史 ──
    qa_history = (
        await db.execute(
            select(QAHistory).where(QAHistory.user_id == user_id).order_by(QAHistory.id)
        )
    ).scalars().all()
    qa_data = [
        {
            "id": q.id,
            "resume_id": q.resume_id,
            "question": q.question,
            "answer": q.answer,
            "created_at": _iso(q.created_at),
        }
        for q in qa_history
    ]

    # ── 求职跟踪 ──
    tracks = (
        await db.execute(select(CampusTrack).where(CampusTrack.user_id == user_id))
    ).scalars().all()
    track_data = [_serialize_row(t) for t in tracks]

    # ── 知识资产 ──
    assets = (
        await db.execute(select(KnowledgeAsset).where(KnowledgeAsset.user_id == user_id))
    ).scalars().all()
    asset_data = [_serialize_row(a) for a in assets]

    # ── 意见箱反馈 + 点赞 ──
    feedbacks = (
        await db.execute(select(UserFeedback).where(UserFeedback.user_id == user_id))
    ).scalars().all()
    feedback_data = [_serialize_row(f) for f in feedbacks]

    likes = (
        await db.execute(select(FeedbackLike).where(FeedbackLike.user_id == user_id))
    ).scalars().all()
    like_data = [_serialize_row(l) for l in likes]

    return {
        "schema_version": 1,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "account": account,
        "resumes": resume_data,
        "qa_history": qa_data,
        "campus_tracks": track_data,
        "knowledge_assets": asset_data,
        "feedback": feedback_data,
        "feedback_likes": like_data,
    }


def _serialize_row(obj) -> dict:
    """ORM 对象 → 字典（时间转 ISO，跳过 None 外键等）。"""
    result = {}
    for column in obj.__table__.columns:
        value = getattr(obj, column.name)
        if hasattr(value, "isoformat"):
            value = value.isoformat()
        result[column.name] = value
    return result


def _iso(value) -> str | None:
    return value.isoformat() if value else None
