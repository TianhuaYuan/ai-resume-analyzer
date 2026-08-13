"""版本化索引器：分块 → embedding → 写入向量库（不可变版本化快照 D2）。

目标：把"单简历流水线"升级为"知识资产库引擎"的可版本化写入路径。

核心语义（不可变版本化快照）：
- 每次索引生成一个"版本快照"：同一 asset 的旧版本 chunks 保留不删（可查旧版本），
  仅把 metadata 中 ``is_latest`` 置 False 完成"退役"。
- chunk id 携带版本号（``{asset_type}_{asset_id}_v{version}_{chunk_index}``），
  避免跨版本 upsert 同 id 互相覆盖。
- collection 由调用方传入（每用户集合命名是 T7 的事，这里解耦）。

依赖（只使用、不修改）：
- ``services.vector_store.get_vector_store``：VectorStore 单例（Protocol 层）
- ``services.rag.chunking.chunk_by_sections``：结构感知分块
- ``services.rag.metadata.build_chunk_metadata``：标准 chunk metadata
- ``services.rag.retrieval.get_embeddings``：批量 embedding（带缓存）
"""

import copy
import logging

from services.rag.chunking import chunk_by_sections
from services.rag.metadata import META_ASSET_ID, META_IS_LATEST, build_chunk_metadata
from services.rag.retrieval import get_embeddings
from services.vector_store import get_vector_store

logger = logging.getLogger(__name__)


async def index_asset(
    *,
    collection: str,
    user_id: int,
    asset_id: int,
    asset_type: str,
    text: str,
    version: int,
    content_hash: str | None = None,
) -> int:
    """分块 → embedding → 写入向量库，返回 chunk 数。

    Args:
        collection: 目标向量集合名（由调用方决定，T7 前与 user 解耦）。
        user_id: 资产所属用户（写入 metadata，用于 T7 每用户集合过滤）。
        asset_id: 资产 ID（如 resume_id）。
        asset_type: 资产类型（如 "resume"）。
        text: 资产全文（将被结构感知分块）。
        version: 新版本号（>=1，首次索引建议传 1）。
        content_hash: 索引时快照的资产哈希。

    Returns:
        写入的 chunk 数（空文本返回 0）。
    """
    store = get_vector_store()

    # ── 1. 查出同 asset 当前最新 chunks（用于旧版本退役）──
    current = await store.get(
        collection,
        where={META_ASSET_ID: asset_id, META_IS_LATEST: True},
    )

    # ── 2. 旧版本退役：深拷贝 metadata 并把 is_latest 置 False（保留不删，可查旧版本）──
    if current:
        retired_ids: list[str] = []
        retired_metadatas: list[dict] = []
        for item in current:
            meta = copy.deepcopy(item["metadata"])
            meta[META_IS_LATEST] = False
            retired_ids.append(item["id"])
            retired_metadatas.append(meta)
        await store.update_metadata(collection, ids=retired_ids, metadatas=retired_metadatas)
        logger.info(
            "索引器：asset %s 退役 %d 个旧 chunk（collection=%s）",
            asset_id,
            len(retired_ids),
            collection,
        )

    # ── 3. 结构感知分块；空文本直接返回 0 ──
    chunks = chunk_by_sections(text)
    if not chunks:
        logger.info("索引器：asset %s 文本为空，跳过写入（collection=%s）", asset_id, collection)
        return 0

    # ── 4. 批量 embedding（第二个参数 asset_id 作为缓存命名空间，按资产隔离）──
    texts = [c["text"] for c in chunks]
    embeddings = await get_embeddings(texts, asset_id)

    # ── 5. chunk id 携带版本号，避免跨版本 upsert 互相覆盖 ──
    ids = [f"{asset_type}_{asset_id}_v{version}_{c['chunk_index']}" for c in chunks]

    # ── 6. 写入新版本 chunks（is_latest=True），metadata 走标准构造 ──
    metadatas = [
        build_chunk_metadata(
            asset_id=asset_id,
            chunk=c,
            user_id=user_id,
            asset_type=asset_type,
            version=version,
            is_latest=True,
            content_hash=content_hash,
        )
        for c in chunks
    ]
    await store.upsert(
        collection,
        ids=ids,
        documents=texts,
        embeddings=embeddings,
        metadatas=metadatas,
    )

    return len(chunks)
