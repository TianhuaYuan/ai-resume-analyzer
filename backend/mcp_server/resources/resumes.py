"""MCP Resource: resume_list / assets_list — 当前用户资产列表（T13 泛化）。"""

import json
import logging

from sqlalchemy import select

from mcp_server.server import get_current_user_id, mcp
from core.database import AsyncSessionLocal
from models.knowledge_asset import KnowledgeAsset
from models.resume import Resume

logger = logging.getLogger(__name__)

# resume 复用 resumes 表（D3），不进入 knowledge_assets 表
_ASSET_TYPE_RESUME = "resume"


@mcp.resource("resume://list")
async def get_resume_list() -> str:
    """获取当前用户的所有简历列表（assets://list 的简历子集，兼容旧调用）。"""

    try:
        user_id = get_current_user_id()
    except LookupError:
        return json.dumps({"error": "authentication required: missing user context"}, ensure_ascii=False)

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Resume).where(Resume.user_id == user_id).order_by(Resume.created_at.desc())
        )
        resumes = result.scalars().all()

    return json.dumps(
        [
            {
                "id": r.id,
                "filename": r.filename,
                "status": r.status,
                "chunk_count": r.chunk_count,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in resumes
        ],
        ensure_ascii=False,
    )


@mcp.resource("assets://list")
async def get_assets_list() -> str:
    """获取当前用户的所有资产，按 asset_type 分组（含版本）。"""

    try:
        user_id = get_current_user_id()
    except LookupError:
        return json.dumps({"error": "authentication required: missing user context"}, ensure_ascii=False)

    async with AsyncSessionLocal() as db:
        resumes_result = await db.execute(
            select(Resume).where(Resume.user_id == user_id).order_by(Resume.created_at.desc())
        )
        resumes = resumes_result.scalars().all()

        assets_result = await db.execute(
            select(KnowledgeAsset)
            .where(KnowledgeAsset.user_id == user_id)
            .order_by(KnowledgeAsset.asset_type, KnowledgeAsset.created_at.desc())
        )
        knowledge_assets = assets_result.scalars().all()

    grouped: dict[str, list[dict]] = {}

    grouped[_ASSET_TYPE_RESUME] = [
        {
            "asset_id": r.id,
            "filename": r.filename,
            "status": r.status,
            "chunk_count": r.chunk_count,
            "version": getattr(r, "index_version", None),
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in resumes
    ]

    for ka in knowledge_assets:
        grouped.setdefault(ka.asset_type, []).append(
            {
                "asset_id": ka.id,
                "title": ka.title,
                "is_draft": ka.is_draft,
                "version": ka.version,
                "index_version": ka.index_version,
                "created_at": ka.created_at.isoformat() if ka.created_at else None,
            }
        )

    return json.dumps(grouped, ensure_ascii=False)
