"""MCP Resource: qa_history — 指定简历的问答历史。"""

import json
import logging

from mcp_server.server import get_current_user_id, mcp

logger = logging.getLogger(__name__)


@mcp.resource("qa_history://{resume_id}")
async def get_qa_history(resume_id: str) -> str:
    """获取指定简历的问答历史记录。"""
    from sqlalchemy import select

    from core.database import AsyncSessionLocal
    from models.qa_history import QAHistory
    from models.resume import Resume

    user_id = get_current_user_id()

    try:
        resume_id_int = int(resume_id)
    except (ValueError, TypeError):
        return json.dumps({"error": f"Invalid resume_id: {resume_id}"})

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Resume).where(Resume.id == resume_id_int, Resume.user_id == user_id)
        )
        resume = result.scalar_one_or_none()

    if resume is None:
        return json.dumps({"error": f"Resume {resume_id} not found or access denied"})

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(QAHistory)
            .where(QAHistory.user_id == user_id, QAHistory.resume_id == resume_id_int)
            .order_by(QAHistory.created_at.desc())
            .limit(50)
        )
        records = result.scalars().all()

    return json.dumps(
        [
            {
                "id": r.id,
                "question": r.question,
                "answer": r.answer,
                "sources": r.sources,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in records
        ],
        ensure_ascii=False,
    )
