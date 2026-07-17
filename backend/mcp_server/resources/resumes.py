"""MCP Resource: resume_list — 当前用户简历列表。"""
import json
import logging

from mcp_server.server import get_current_user_id, mcp

logger = logging.getLogger(__name__)


@mcp.resource("resume://list")
async def get_resume_list() -> str:
    """获取当前用户的所有简历列表。"""
    from sqlalchemy import select

    from core.database import AsyncSessionLocal
    from models.resume import Resume

    user_id = get_current_user_id()

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Resume)
            .where(Resume.user_id == user_id)
            .order_by(Resume.created_at.desc())
        )
        resumes = result.scalars().all()

    return json.dumps([
        {
            "id": r.id,
            "filename": r.filename,
            "status": r.status,
            "chunk_count": r.chunk_count,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in resumes
    ], ensure_ascii=False)
