"""assets.py — 知识资产 CRUD API（T3, D2 脏标记模式 + 懒索引触发）。

JD / 面试记录 / 笔记三类求职知识资产的增删改查：
- 创建/更新写 ``content_hash = sha256(content)`` 启用脏标记（D2），
  从此 ensure_indexed 只在 content_hash != indexed_hash 时才重建向量；
- 非草稿（is_draft=False）落库后懒触发 ensure_indexed（同 session，内部 commit）；
- 草稿（is_draft=True）只进工作区不建索引（D3 草稿隔离）；
- 删除时清 MySQL 行 + 清 knowledge_{user_id} 集合内该资产全部 chunks。

错误码统一走 AppException（core/exceptions.py），非本人资产一律 404（防枚举）。
"""

import logging

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_current_user
from core.database import get_db
from core.exceptions import AppException
from models.knowledge_asset import KnowledgeAsset
from models.user import User
from schemas.assets import (
    ASSET_TYPES,
    AssetCreate,
    AssetListResponse,
    AssetResponse,
    AssetUpdate,
)
from services.rag.clients import knowledge_collection_name
from services.rag.ensure_indexed import ensure_indexed
from services.rag.metadata import META_ASSET_ID, META_ASSET_TYPE
from services.vector_store import get_vector_store
from services import asset_service
from services.audit_log_service import write_audit_log

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/assets", tags=["assets"])


async def _get_owned_asset(
    db: AsyncSession, asset_id: int, user_id: int
) -> KnowledgeAsset:
    """查资产并校验归属；不存在或非本人 → 404（防枚举）。"""
    asset = await db.get(KnowledgeAsset, asset_id)
    if asset is None or asset.user_id != user_id:
        raise AppException(status_code=404, detail="资产不存在或无权访问")
    return asset


@router.post("", response_model=AssetResponse, status_code=status.HTTP_201_CREATED)
async def create_asset(
    request: Request,
    body: AssetCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """创建知识资产（职责重定位：手动新建仅支持笔记 note）。

    - JD / 面试记录不再支持手动创建：JD 从投递看板归档、面试记录从面试复盘归档
      （POST /job-applications/{id}/archive、POST /interviews/{id}/archive）
    - 写 content_hash = sha256(content) 启用脏标记
    - is_draft=False → 懒触发 ensure_indexed 重建向量

    错误码：
    - 401 未登录
    - 400 asset_type 非 note（JD / 面试记录走归档）
    - 500 向量化重建失败（ensure_indexed 内部降级，不阻断落库）
    """
    if body.asset_type != "note":
        raise AppException(
            status_code=400,
            detail="手动新建仅支持笔记（note）；JD / 面试记录请从投递看板 / 面试复盘归档",
        )

    asset = await asset_service.create_asset(
        db,
        current_user.id,
        asset_type=body.asset_type,
        title=body.title,
        content=body.content,
        is_draft=body.is_draft,
    )
    await write_audit_log(
        db,
        user_id=current_user.id,
        action="asset_create",
        target_type="asset",
        target_id=str(asset.id),
        detail={"result": "success", "request_id": request.headers.get("X-Request-ID"), "asset_type": asset.asset_type},
        ip=request.client.host if request.client else None,
    )
    return AssetResponse.model_validate(asset)


@router.get("", response_model=AssetListResponse)
async def list_assets(
    asset_type: str | None = Query(None, description="按资产类型过滤（jd/interview/note）"),
    page: int = Query(1, ge=1, description="页码，>=1"),
    limit: int = Query(20, ge=1, le=50, description="每页数量，1-50"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """当前用户的知识资产分页列表，按 updated_at 倒序。

    asset_type 可选过滤；page>=1、limit 1-50。

    错误码：
    - 401 未登录
    - 400 非法 asset_type
    """
    conditions = [KnowledgeAsset.user_id == current_user.id]
    if asset_type:
        if asset_type not in ASSET_TYPES:
            raise AppException(
                status_code=400,
                detail=f"非法 asset_type: {asset_type}，仅支持 {', '.join(ASSET_TYPES)}",
            )
        conditions.append(KnowledgeAsset.asset_type == asset_type)

    total = (
        await db.execute(
            select(func.count()).select_from(KnowledgeAsset).where(*conditions)
        )
    ).scalar_one()

    result = await db.execute(
        select(KnowledgeAsset)
        .where(*conditions)
        .order_by(KnowledgeAsset.updated_at.desc())
        .offset((page - 1) * limit)
        .limit(limit)
    )
    rows = result.scalars().all()

    return AssetListResponse(
        items=[AssetResponse.model_validate(a) for a in rows],
        total=total,
        page=page,
        limit=limit,
    )


@router.get("/{asset_id}", response_model=AssetResponse)
async def get_asset(
    asset_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """查单个资产详情；非本人 → 404（防枚举）。"""
    asset = await _get_owned_asset(db, asset_id, current_user.id)
    return AssetResponse.model_validate(asset)


@router.put("/{asset_id}", response_model=AssetResponse)
async def update_asset(
    request: Request,
    asset_id: int,
    body: AssetUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """部分更新资产（title / content / is_draft）。

    - content 变 → 重算 content_hash + version+=1 + indexed_hash=None（索引过期，触发懒重建）
    - 最终 is_draft=False → 调 ensure_indexed
    - 非本人 → 404

    错误码：
    - 401 未登录
    - 404 资产不存在或非本人
    """
    asset = await _get_owned_asset(db, asset_id, current_user.id)

    if body.title is not None:
        asset.title = body.title
    if body.content is not None:
        asset.content = body.content
        asset.content_hash = asset_service._sha256(body.content)
        asset.version += 1
        asset.indexed_hash = None  # 索引过期 → 懒重建
    if body.is_draft is not None:
        asset.is_draft = body.is_draft

    await db.commit()
    await db.refresh(asset)

    if not asset.is_draft:
        await ensure_indexed(
            db,
            user_id=current_user.id,
            asset_id=asset.id,
            asset_type=asset.asset_type,
            collection=knowledge_collection_name(current_user.id),
        )
        # 同 create：ensure_indexed 失败路径会 rollback（expire ORM 对象），重读一次
        await db.refresh(asset)

    await write_audit_log(
        db,
        user_id=current_user.id,
        action="asset_update",
        target_type="asset",
        target_id=str(asset.id),
        detail={"result": "success", "request_id": request.headers.get("X-Request-ID")},
        ip=request.client.host if request.client else None,
    )

    return AssetResponse.model_validate(asset)


@router.delete("/{asset_id}", status_code=204)
async def delete_asset(
    request: Request,
    asset_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """删除资产：删 MySQL 行 + 清向量 chunks。

    只删 knowledge_{user_id} 集合内该资产的 chunks（按 asset_id + asset_type），
    不误删同用户其他资产。非本人 → 404。

    错误码：
    - 401 未登录
    - 404 资产不存在或非本人
    """
    asset = await _get_owned_asset(db, asset_id, current_user.id)
    asset_type = asset.asset_type  # 提前提取，避免 commit 后访问 expired 属性

    await db.delete(asset)
    await db.commit()

    # 清向量：行已删除，向量清理 best-effort（失败仅 warning，不把成功删除回退成 500）
    try:
        await get_vector_store().delete(
            knowledge_collection_name(current_user.id),
            where={META_ASSET_ID: asset_id, META_ASSET_TYPE: asset_type},
        )
    except Exception:
        logger.warning("Failed to delete asset vectors: asset=%d type=%s", asset_id, asset_type)

    await write_audit_log(
        db,
        user_id=current_user.id,
        action="asset_delete",
        target_type="asset",
        target_id=str(asset_id),
        detail={"result": "success", "request_id": request.headers.get("X-Request-ID"), "asset_type": asset_type},
        ip=request.client.host if request.client else None,
    )

    return None
