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

from rank_bm25 import BM25Okapi

from services.rag.chunking import tokenize
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
MEM_EXPIRED = "expired"  # A3: 失效标记（true=过期/被推翻，默认召回隐藏）

# 默认记忆层级：L4 全部归 episodic（原始情节），L3 画像为压缩后的 semantic
DEFAULT_TIER = "episodic"
DEFAULT_IMPORTANCE = 0.5
# 召回分数阈值：低于视为噪声
DEFAULT_RECALL_THRESHOLD = 0.5
# F2 三信号召回（mem0 借鉴）加性融合权重（总和=1.0）：向量 / 实体命中 / BM25。
# 权重为可调常量：调高 W_BM25 强化关键词命中，调高 W_VECTOR 强化语义泛化。
# entity 与 vector 对等：query 明确命中实体名是强意图锚点，应能压过不相关的向量噪声。
W_VECTOR = 0.4
W_ENTITY = 0.4
W_BM25 = 0.2


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
    show_expired: bool = False,
) -> list[dict]:
    """按语义召回用户记忆片段（按用户隔离 + 分数阈值过滤）。

    A3 失效不删除（借鉴 mem0 expiration 隐藏 + graphiti invalid_at 保留历史）：
    默认过滤 expired 标记的记忆；show_expired=True 可见全部（审计/回溯）。

    Returns:
        ``[{memory_id, text, score, metadata}, ...]``，按相似度降序。
    """
    embedding = (await get_embeddings([query], user_id))[0]
    items = await get_vector_store().query(_collection(user_id), embedding, top_k)
    out: list[dict] = []
    for item in items:
        if item["score"] >= threshold:
            meta = item["metadata"] or {}
            if not show_expired and meta.get(MEM_EXPIRED) is True:
                continue  # 失效记忆默认隐藏（保留历史，不删除）
            out.append(
                {
                    "memory_id": item["id"],
                    "text": item["text"],
                    "score": item["score"],
                    "metadata": meta,
                }
            )
    return out


# ═══════════════════════════════════════════════════════════════
# F2 三信号召回（mem0 借鉴）：向量 / 实体 / BM25 加性融合
# ═══════════════════════════════════════════════════════════════


def score_bm25(query: str, texts: list[str]) -> list[float]:
    """BM25 关键词分（复用 retrieval.py 同款 rank_bm25 + jieba 分词）。

    对候选文本集整体构建索引（候选集重排模式，不建全库持久索引），
    返回与 texts 一一对应的原始 BM25 分（未归一化，由融合层统一归一化）。
    空分词 / 退化输入（如 avgdl=0）返回全 0，不抛异常，保证召回链路不中断。
    """
    if not texts:
        return []
    tokenized = [tokenize(t or "") for t in texts]
    if not any(tokenized):
        return [0.0] * len(texts)
    query_tokens = tokenize(query or "")
    if not query_tokens:
        return [0.0] * len(texts)
    try:
        index = BM25Okapi(tokenized)
    except Exception as e:  # 退化输入不阻塞召回
        logger.debug("BM25 构建失败（降级为全 0 分）: %s", e)
        return [0.0] * len(texts)
    return [float(s) for s in index.get_scores(query_tokens)]


def _normalize_by_max(scores: list[float | None]) -> list[float]:
    """信号归一化到 [0,1]：按池内最大值缩放；None 视为缺失 → 0。

    全缺失 / 全 0（无可区分度）→ 全 0（中性，不干扰排序）。
    """
    present = [s for s in scores if s is not None]
    if not present:
        return [0.0] * len(scores)
    hi = max(present)
    if hi <= 1e-12:
        return [0.0] * len(scores)
    return [(s / hi if s is not None else 0.0) for s in scores]


def fuse_three_signals(
    candidates: list[dict],
    *,
    w_vector: float = W_VECTOR,
    w_entity: float = W_ENTITY,
    w_bm25: float = W_BM25,
) -> list[dict]:
    """三信号加性融合（mem0 借鉴），返回新 dict 列表（含 score + score_details），按融合分降序。

    信号取值约定（同一 [0,1] 量纲，权重才可解释）：
    - ``vector``：embedding 余弦相似度原值（clamp 0-1，来自 recall_memory）
    - ``entity``：直接实体命中强度 0.5 + 0.5*importance（命中即强相关，最低 0.5）
    - ``bm25``：池内按最大值归一化到 [0,1]
    某信号全局缺失时，其权重在剩余信号间重归一化（总和仍为 1），避免分数被整体压扁。

    Args:
        candidates: ``[{text, vector: float|None, entity: float|None, bm25: float|None, **base}]``

    Returns:
        ``[{**base, score, score_details: {vector, entity, bm25, fused, weights}}]``，
        按 ``score`` 降序（同分保持输入顺序稳定）。
    """
    if not candidates:
        return []
    bm25_norm = _normalize_by_max([c.get("bm25") for c in candidates])
    weights = {"vector": float(w_vector), "entity": float(w_entity), "bm25": float(w_bm25)}
    base_weight_sum = weights["vector"] + weights["entity"] + weights["bm25"]

    out: list[dict] = []
    for i, c in enumerate(candidates):
        vec = min(max(c.get("vector") or 0.0, 0.0), 1.0)
        ent = min(max(c.get("entity") or 0.0, 0.0), 1.0)
        # per-candidate 权重重归一化：某候选缺失的信号，其权重在该候选自身剩余
        # 信号间重新分配（避免「缺 vector 的实体事实」被全局权重压低）；
        # 三信号齐全的候选权重不变（total=1）。
        avail_c = {
            "vector": c.get("vector") is not None,
            "entity": c.get("entity") is not None,
            "bm25": c.get("bm25") is not None,
        }
        total_c = sum(weights[k] for k, ok in avail_c.items() if ok)
        if total_c <= 0:
            total_c = base_weight_sum
        scaled_c = {k: (weights[k] / total_c if avail_c[k] else 0.0) for k in weights}
        fused = scaled_c["vector"] * vec + scaled_c["entity"] * ent + scaled_c["bm25"] * bm25_norm[i]
        item = dict(c)
        item["score"] = round(fused, 4)
        item["score_details"] = {
            "vector": round(vec, 4),
            "entity": round(ent, 4),
            "bm25": round(bm25_norm[i], 4),
            "fused": round(fused, 4),
            "weights": {k: round(v, 4) for k, v in scaled_c.items()},
        }
        out.append(item)
    out.sort(key=lambda x: x["score"], reverse=True)
    return out


async def expire_memory(user_id: int, memory_id: str) -> None:
    """A3: 标记记忆失效（失效不删除，保留历史回溯——对齐 graphiti invalid_at）。

    与 delete_memory 的区别：expired 仅隐藏于默认召回，数据保留；
    同内容重新保存（save_memory hash 覆盖）会自动复活。
    """
    await get_vector_store().update_metadata(
        _collection(user_id),
        ids=[memory_id],
        metadatas=[{MEM_EXPIRED: True}],
    )
    logger.info("L4 记忆标记失效: user=%d id=%s", user_id, memory_id)


async def delete_memory(user_id: int, memory_id: str) -> None:
    """删除一条记忆（隐私：用户可随时清除）。"""
    await get_vector_store().delete(
        _collection(user_id),
        where={"memory_id": memory_id},
    )
