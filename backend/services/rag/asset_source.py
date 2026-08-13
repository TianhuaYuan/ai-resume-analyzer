"""资产源文本解析。

检索/索引/整文直读统一按 (asset_type, asset_id) 取源，不关心实体存哪张表：
- asset_type == "resume"   → resumes.parsed_text（复用现有表，D3）
- 其他（jd / interview / note）→ knowledge_assets.content（通用表）

归属校验（user_id）也走这里，供 scope 检索 / MCP 鉴权复用（D7）。
"""

from sqlalchemy.ext.asyncio import AsyncSession

from models.knowledge_asset import KnowledgeAsset
from models.resume import Resume

ASSET_TYPE_RESUME = "resume"


async def resolve_asset_text(
    db: AsyncSession,
    asset_type: str,
    asset_id: int,
) -> str | None:
    """按资产类型取源文本；资产不存在返回 None。"""
    if asset_type == ASSET_TYPE_RESUME:
        row = await db.get(Resume, asset_id)
        return row.parsed_text if row else None
    row = await db.get(KnowledgeAsset, asset_id)
    return row.content if row else None


async def resolve_asset_user_id(
    db: AsyncSession,
    asset_type: str,
    asset_id: int,
) -> int | None:
    """取资产归属 user_id，用于越权校验；资产不存在返回 None。"""
    if asset_type == ASSET_TYPE_RESUME:
        row = await db.get(Resume, asset_id)
        return row.user_id if row else None
    row = await db.get(KnowledgeAsset, asset_id)
    return row.user_id if row else None
