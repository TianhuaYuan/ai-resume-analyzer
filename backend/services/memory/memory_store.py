"""L4 向量语义记忆存储（T15, D8）。

- 集合：``memory_{user_id}``（每用户一个，entry 粒度）
- 一条记忆 = 一个 entry，``id = sha256(内容)`` 前 32 位 → upsert 幂等（同内容不重复）
- metadata：``{user_id, tier, type, importance, created_at, last_accessed_at, ttl}``
- 写：save_memory；读：recall_memory（语义召回 + metadata 过滤 + 分数阈值）
- 无 chunk 污染问题：entry 粒度天然稳定，upsert 即覆盖

T16 的合并/衰减/过期在此基础上扩展（last_accessed_at / importance / ttl）。
"""

import hashlib
import logging
import time

from services.rag.retrieval import get_embeddings
from services.vector_store import get_vector_store

logger = logging.getLogger(__name__)

# memory metadata 字段名
MEM_ID = "memory_id"
MEM_USER_ID = "user_id"
MEM_TIER = "tier"
MEM_TYPE = "type"
MEM_IMPORTANCE = "importance"
MEM_CREATED_AT = "created_at"
MEM_LAST_ACCESSED = "last_accessed_at"
MEM_TTL = "ttl"

# 默认记忆层级：L4 全部归 episodic（原始情节），L3 画像为压缩后的 semantic
DEFAULT_TIER = "episodic"
DEFAULT_IMPORTANCE = 0.5
# 召回分数阈值：低于视为噪声
DEFAULT_RECALL_THRESHOLD = 0.5


def _collection(user_id: int) -> str:
    return f"memory_{user_id}"


def _memory_id(snippet: str) -> str:
    return hashlib.sha256(snippet.encode("utf-8")).hexdigest()[:32]


async def save_memory(
    *,
    user_id: int,
    snippet: str,
    memory_type: str = "episodic",
    importance: float = DEFAULT_IMPORTANCE,
    ttl: int | None = None,
) -> str:
    """写入一条长期记忆（幂等：同内容 hash id 覆盖）。返回 memory id。

    Args:
        user_id: 所属用户。
        snippet: 独立的原子事实（应无上下文依赖，可直接检索）。
        memory_type: episodic（原始情节）/ semantic（提炼后的语义事实）。
        importance: 重要度 0-1。
        ttl: 过期秒数（None = 永久；T16 衰减据此）。
    """
    snippet = (snippet or "").strip()
    if not snippet:
        raise ValueError("snippet 不能为空")

    mid = _memory_id(snippet)
    embedding = (await get_embeddings([snippet], user_id))[0]
    now = int(time.time())
    meta: dict = {
        MEM_ID: mid,
        MEM_USER_ID: user_id,
        MEM_TIER: DEFAULT_TIER,
        MEM_TYPE: memory_type,
        MEM_IMPORTANCE: float(importance),
        MEM_CREATED_AT: now,
        MEM_LAST_ACCESSED: now,
    }
    if ttl:
        meta[MEM_TTL] = int(ttl)

    await get_vector_store().upsert(
        _collection(user_id),
        ids=[mid],
        documents=[snippet],
        embeddings=[embedding],
        metadatas=[meta],
    )
    logger.info("L4 记忆写入: user=%d id=%s len=%d", user_id, mid, len(snippet))
    return mid


async def recall_memory(
    *,
    user_id: int,
    query: str,
    top_k: int = 5,
    threshold: float = DEFAULT_RECALL_THRESHOLD,
) -> list[dict]:
    """按语义召回用户记忆片段（按用户隔离 + 分数阈值过滤）。

    Returns:
        ``[{memory_id, text, score, metadata}, ...]``，按相似度降序。
    """
    embedding = (await get_embeddings([query], user_id))[0]
    items = await get_vector_store().query(_collection(user_id), embedding, top_k)
    out: list[dict] = []
    for item in items:
        if item["score"] >= threshold:
            out.append(
                {
                    "memory_id": item["id"],
                    "text": item["text"],
                    "score": item["score"],
                    "metadata": item["metadata"],
                }
            )
    return out


async def delete_memory(user_id: int, memory_id: str) -> None:
    """删除一条记忆（隐私：用户可随时清除）。"""
    await get_vector_store().delete(
        _collection(user_id),
        where={"memory_id": memory_id},
    )
