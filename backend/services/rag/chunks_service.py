"""简历分块查询服务。

从 ChromaDB 每用户集合（knowledge_{user_id}）读取指定简历（asset_id）的最新
chunks，组装成统一的 dict 列表返回。

注意：
- ChromaDB PersistentClient 非线程安全，所有操作必须走 with_chroma 全局锁
- collection 可能不存在（简历 status=processing 或向量未建好）→ 抛 409
- chunks 不在 MySQL，归属校验由调用方（端点）通过 resume_service.get_resume 完成
"""

import logging

from fastapi import HTTPException, status

from services.rag.clients import knowledge_collection_name
from services.rag.metadata import META_ASSET_ID, META_IS_LATEST
from services.vector_store import get_vector_store

logger = logging.getLogger(__name__)


async def get_chunks_by_resume(user_id: int, resume_id: int) -> list[dict]:
    """读取指定简历的所有 chunks（每用户集合内按 asset_id + is_latest 过滤）。

    返回结构：
        [{"chunk_index": int, "section": str, "text": str,
          "start_char": int, "end_char": int}, ...]

    按 chunk_index 升序排列。

    异常：
        HTTPException 409 - collection 不存在（简历未就绪或向量未建好）
    """
    name = knowledge_collection_name(user_id)
    items = await get_vector_store().get(
        name,
        where={META_ASSET_ID: resume_id, META_IS_LATEST: True},
    )

    if items is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="简历向量未就绪，请稍后重试",
        )

    chunks: list[dict] = []
    for item in items:
        meta = item["metadata"]
        chunks.append(
            {
                "chunk_index": int(meta.get("chunk_index", 0)),
                "section": str(meta.get("section", "")),
                "text": str(item["text"]),
                "start_char": int(meta.get("start_char", 0)),
                "end_char": int(meta.get("end_char", 0)),
            }
        )

    # 按 chunk_index 升序（Chroma 不保证返回顺序）
    chunks.sort(key=lambda c: c["chunk_index"])
    return chunks
