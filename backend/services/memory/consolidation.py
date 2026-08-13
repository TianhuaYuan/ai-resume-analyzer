"""记忆合并/衰减。

A3 失效不删除（ 隐藏 + graphiti invalid_at 保留历史）：
- 过期标记：``last_accessed_at + ttl < now`` → 标记 expired=true（默认召回隐藏，
  数据保留供回溯；同内容重新保存自动复活）——不再物理删除
- 语义去重合并：两条记忆相似度超过阈值 → 保留重要度高的，删除另一条
  （重复不是历史，物理删除合理）
- 不引 APScheduler：调度复用 RabbitMQ consumer 模式（后台定时任务），本模块只做逻辑

注意：conversation 依赖的原始 L2 历史（qa_history）由 SQL 存储，不受影响；
这里只做 L4 记忆集合内的整理。
"""

import logging
import time

from services.memory.memory_store import (
    MEM_IMPORTANCE,
    MEM_LAST_ACCESSED,
    MEM_TTL,
    _collection,
)
from services.rag.retrieval import get_embeddings
from services.vector_store import get_vector_store

logger = logging.getLogger(__name__)

# 语义去重合并阈值：两条记忆 embedding 余弦相似度 >= 此值视为重复
_DUP_MERGE_THRESHOLD = 0.95


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    if not na or not nb:
        return 0.0
    return dot / (na * nb)


async def consolidate(user_id: int) -> dict:
    """整理用户 L4 记忆：过期标记（失效不删除）+ 相似合并。返回统计。

    A3: expired 改为标记而非删除（对齐 graphiti 失效不删除机制），
    历史数据保留，默认召回隐藏。

    Returns:
        {"expired": int, "merged": int, "deleted": int, "remaining": int}
    """
    store = get_vector_store()
    collection = _collection(user_id)
    items = await store.get(collection)
    if not items:
        return {"expired": 0, "merged": 0, "deleted": 0, "remaining": 0}

    now = int(time.time())

    # ── 1. 过期标记（ttl 且 最后访问距今超期 → expired=true，不删除）──
    from services.memory.memory_store import expire_memory

    expired_ids: list[str] = []
    for item in items:
        meta = item["metadata"] or {}
        ttl = meta.get(MEM_TTL)
        if ttl:
            last = int(meta.get(MEM_LAST_ACCESSED, 0))
            if now - last > int(ttl):
                expired_ids.append(item["id"])
    for cid in expired_ids:
        await expire_memory(user_id, cid)
        logger.info("L4 记忆过期标记（保留历史）: user=%d id=%s", user_id, cid)

    # ── 2. 语义去重合并（保留重要度高的，删除另一条；已过期的不参与合并）──
    live_items = [it for it in items if it["id"] not in set(expired_ids)]
    dup_to_delete: set[str] = set()  # 修复：live_items ≤ 1 时块外统计仍可引用
    if len(live_items) > 1:
        embeddings = await get_embeddings([it["text"] for it in live_items], user_id)
        for i in range(len(live_items)):
            if live_items[i]["id"] in dup_to_delete:
                continue
            for j in range(i + 1, len(live_items)):
                if live_items[j]["id"] in dup_to_delete:
                    continue
                sim = _cosine(embeddings[i], embeddings[j])
                if sim >= _DUP_MERGE_THRESHOLD:
                    imp_i = float(live_items[i]["metadata"].get(MEM_IMPORTANCE, 0.5))
                    imp_j = float(live_items[j]["metadata"].get(MEM_IMPORTANCE, 0.5))
                    loser = live_items[j] if imp_i >= imp_j else live_items[i]
                    dup_to_delete.add(loser["id"])
        for cid in dup_to_delete:
            await store.delete(collection, where={"memory_id": cid})

    remaining = len(items) - len(dup_to_delete)  # expired 仅标记不删除（A3）
    logger.info(
        "L4 consolidation: user=%d 过期标记=%d 合并删除=%d 剩余=%d",
        user_id, len(expired_ids), len(dup_to_delete), remaining,
    )
    return {
        "expired": len(expired_ids),
        "merged": len(dup_to_delete),
        "deleted": len(dup_to_delete),  # 物理删除仅限重复合并
        "remaining": remaining,
    }
