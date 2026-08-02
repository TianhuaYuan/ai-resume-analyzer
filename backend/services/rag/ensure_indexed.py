"""懒索引入口（T6, D3 草稿工作区隔离 + 懒索引 + D2 版本化快照；T8 兜底）。

脏标记：``content_hash != indexed_hash`` → 索引过期。

``ensure_indexed`` 是唯一索引入口：RAG 检索（经典 QA / agentic search_resume）
与 complete 预热共用。并发经 per-asset 分布式锁去重（Redis）；
重建失败保留旧索引（``indexed_hash`` 不更新），调用方用 ``is_stale`` 声明降级。

T8 兜底：脏标记干净不代表向量库有数据（崩溃在 commit 与索引之间、或手动删库）。
``_is_ready`` 额外校验 collection 确有该资产最新 chunks，缺失则强制重建。
"""

import asyncio
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from core.distributed_lock import acquire_index_lock, release_index_lock
from models.knowledge_asset import KnowledgeAsset
from models.resume import Resume
from services.rag.asset_source import ASSET_TYPE_RESUME
from services.rag.indexer import index_asset
from services.rag.metadata import META_ASSET_ID, META_IS_LATEST
from services.rag.retrieval import clear_bm25
from services.vector_store import get_vector_store

logger = logging.getLogger(__name__)

# 锁忙时轮询等待重建完成的最多次数 / 间隔（秒）
_LOCK_BUSY_RETRIES = 5
_LOCK_BUSY_INTERVAL = 0.5


async def _load_asset(
    db: AsyncSession, asset_type: str, asset_id: int
) -> tuple[object | None, str]:
    """加载资产行 + 源文本；不存在返回 (None, "")。"""
    if asset_type == ASSET_TYPE_RESUME:
        row = await db.get(Resume, asset_id)
        return row, (row.parsed_text if row else "")
    # 注意：知识资产启用时其创建路径须写 content_hash（sha256(content)）以启用脏标记；
    # 当前 knowledge_assets 表无业务写入路径，content_hash 恒为 None → 每次检索都会重建。
    row = await db.get(KnowledgeAsset, asset_id)
    return row, (row.content if row else "")


async def _is_ready(row: object, collection: str, asset_id: int) -> bool:
    """索引就绪判定（T8 兜底）：脏标记干净 AND collection 确有该资产最新 chunks。

    只有 DB 脏标记一致还不够——若向量集合被删/未建成（崩溃窗口、手动清理），
    会误判就绪导致检索空结果。此时返回 False 走强制重建。
    """
    if not (bool(row.content_hash) and row.content_hash == row.indexed_hash):
        return False
    existing = await get_vector_store().get(
        collection,
        where={META_ASSET_ID: asset_id, META_IS_LATEST: True},
    )
    return bool(existing)


async def ensure_indexed(
    db: AsyncSession,
    *,
    user_id: int,
    asset_id: int,
    asset_type: str,
    collection: str,
) -> bool:
    """确保资产向量索引与当前内容一致（懒触发重建）。

    Returns:
        True：索引就绪（本来干净，或刚重建成功，或另一请求正在重建）；
        False：重建失败，调用方应降级（is_stale 声明 / 拒答 / 提示重试）。
    """
    # ── 1. 就绪判定（脏标记 + 向量数据双重校验）；就绪则直接返回 ──
    row, text = await _load_asset(db, asset_type, asset_id)
    if row is None:
        return False
    if await _is_ready(row, collection, asset_id):
        return True
    if not text:
        logger.warning("ensure_indexed: asset %s 无内容，跳过", asset_id)
        return False

    # ── 2. 获取 per-asset 分布式锁（防并发重建）──
    lock_id = await acquire_index_lock(user_id, asset_type, asset_id)
    if lock_id is None:
        # 另一请求正在重建：轮询等待其完成
        for _ in range(_LOCK_BUSY_RETRIES):
            await asyncio.sleep(_LOCK_BUSY_INTERVAL)
            fresh_row, _ = await _load_asset(db, asset_type, asset_id)
            if fresh_row is not None and await _is_ready(fresh_row, collection, asset_id):
                return True
        logger.info(
            "ensure_indexed: 锁忙等待超时，返回就绪（可能有短暂陈旧索引）asset=%s", asset_id
        )
        return True

    try:
        # ── 3. 锁内二次校验（另一请求可能已完成重建）──
        row, text = await _load_asset(db, asset_type, asset_id)
        if row is None:
            return False
        if await _is_ready(row, collection, asset_id):
            return True

        # ── 4. 版本化重建（version 单调递增，独立于 document version）──
        new_version = (row.index_version or 0) + 1
        chunk_count = await index_asset(
            collection=collection,
            user_id=user_id,
            asset_id=asset_id,
            asset_type=asset_type,
            text=text,
            version=new_version,
            content_hash=row.content_hash,
        )

        # ── 5. 成功才更新 indexed_hash / index_version / chunk_count（失败保留旧索引可重试）──
        row.indexed_hash = row.content_hash
        row.index_version = new_version
        if hasattr(row, "chunk_count"):
            row.chunk_count = chunk_count  # 懒重建后同步 chunk 数（信息性字段）
        await db.commit()
        # 重建后清 BM25 缓存（旧版本内容已退役，避免污染）
        await clear_bm25(user_id, asset_id)
        logger.info(
            "ensure_indexed: 重建完成 asset=%s v%d chunks=%d",
            asset_id, new_version, chunk_count,
        )
        return True
    except Exception as e:
        await db.rollback()
        logger.exception("ensure_indexed: 重建失败 asset=%s: %s", asset_id, e)
        return False
    finally:
        await release_index_lock(user_id, asset_type, asset_id, lock_id)
