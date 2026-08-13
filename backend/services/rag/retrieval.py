"""检索与排序：Embedding 向量化 / BM25 关键词 / 混合检索(RRF) / Cross-Encoder 重排 / 拒答判定。

阶段11 从 rag_service.py 拆出：所有与"从简历里找出相关段落"相关的能力都集中于此，
是自包含、可直接单测的核心检索层。
"""

import asyncio
import logging
from collections import OrderedDict
from typing import Any

import httpx
from rank_bm25 import BM25Okapi

from core import cache as embedding_cache
from core.config import settings

# 模块级 httpx 客户端，复用 TCP 连接，避免每次 rerank 调用创建/销毁连接
_http_client: httpx.AsyncClient | None = None
_http_client_lock = asyncio.Lock()


async def _get_http_client() -> httpx.AsyncClient:
    """获取或创建模块级 httpx 客户端（单例，连接池复用）。

    P1-11：加锁避免 TOCTOU 竞态，多协程并发调用只会创建一个实例。
    """
    global _http_client
    async with _http_client_lock:
        if _http_client is None or _http_client.is_closed:
            _http_client = httpx.AsyncClient(timeout=30)
    return _http_client
from core.retry import with_retry
from services.rag.chunking import tokenize
from services.rag.clients import get_embedding_client, knowledge_collection_name
from services.rag.metadata import (
    ASSET_TYPE_RESUME,
    META_ASSET_ID,
    META_IS_LATEST,
)
from services.vector_store import get_vector_store

logger = logging.getLogger(__name__)

_bm25_indexes: OrderedDict[int, tuple[BM25Okapi, list[dict]]] = OrderedDict()
_BM25_MAX_SIZE = 50  # LRU 上限，防止内存无限增长
_bm25_lock = asyncio.Lock()


async def get_embeddings(texts: list[str], resume_id: int | None = None) -> list[list[float]]:
    """批量调 Embedding API（模型由 settings.EMBEDDING_MODEL 决定），缓存命中跳过 API 调用。resume_id 用于按简历追踪缓存。"""
    vectors: list[list[float]] = []
    uncached_idx: list[int] = []
    uncached: list[str] = []

    for i, t in enumerate(texts):
        vec = await embedding_cache.get_embedding(t)
        if vec is not None:
            vectors.append(vec)
        else:
            vectors.append([])  # placeholder，下面批量填
            uncached_idx.append(i)
            uncached.append(t)

    if uncached:
        client = get_embedding_client()
        for batch_start in range(0, len(uncached), 10):
            batch_texts = uncached[batch_start : batch_start + 10]
            batch_idx = uncached_idx[batch_start : batch_start + 10]
            response = await client.embeddings.create(
                model=settings.EMBEDDING_MODEL,
                input=batch_texts,
            )
            for j, item in enumerate(response.data):
                idx = batch_idx[j]
                vectors[idx] = item.embedding
                await embedding_cache.set_embedding(batch_texts[j], item.embedding, resume_id)

    return vectors


async def _load_bm25_index(
    collection: str,
    where: dict[str, Any],
    store_key: str,
) -> bool:
    """从向量库按 where 过滤读取文档构建 BM25 索引，返回是否加载成功。

    T7：BM25 只构建 scope 命中的资产 + is_latest 快照，避免旧版本/他人内容污染。
    """
    items = await get_vector_store().get(collection, where=where)
    if items is None:
        logger.warning("Chroma collection %s not found, skip BM25 build", collection)
        return False
    chunks = []
    for item in items:
        meta = item["metadata"]
        chunks.append(
            {
                "text": item["text"],
                "chunk_index": meta["chunk_index"],
                "section": meta["section"],
                # B3：跨 asset 的公共集合里 chunk_index 会重复，稀疏结果带上
                # asset_id/version 供复合键（asset_id, chunk_index）去重合并
                "asset_id": meta.get("asset_id"),
                "version": meta.get("version"),
            }
        )
    if not chunks:
        return False
    tokenized = [tokenize(c["text"]) for c in chunks]
    # LRU 淘汰：超过上限时删除最久未使用的条目
    if store_key in _bm25_indexes:
        _bm25_indexes.move_to_end(store_key)
    _bm25_indexes[store_key] = (BM25Okapi(tokenized), chunks)
    while len(_bm25_indexes) > _BM25_MAX_SIZE:
        _bm25_indexes.popitem(last=False)
    return True


async def _keyword_search(
    collection: str,
    where: dict[str, Any],
    store_key: str,
    question: str,
    top_k: int,
) -> list[dict]:
    """BM25 关键词检索：懒加载索引 → 分词算分 → 返回 top_k，过滤零分结果。"""
    async with _bm25_lock:
        if store_key not in _bm25_indexes:
            if not await _load_bm25_index(collection, where, store_key):
                return []
        # LRU：访问时 move_to_end，标记为最近使用
        if store_key in _bm25_indexes:
            _bm25_indexes.move_to_end(store_key)
        # H2 修复：将 _bm25_indexes.get() 的读取纳入锁临界区，
        # 避免与 clear_bm25 的 pop 产生数据竞争
        index_data = _bm25_indexes.get(store_key)
    if index_data is None:
        return []
    index, chunks = index_data
    scores = index.get_scores(tokenize(question))
    top_indices = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:top_k]
    return [
        {
            "text": chunks[i]["text"],
            "score": float(scores[i]),
            "chunk_index": chunks[i]["chunk_index"],
            "section": chunks[i]["section"],
            "source": "sparse",
            # B3：与稠密结果对齐，供公共集合复合键合并
            "asset_id": chunks[i].get("asset_id"),
            "version": chunks[i].get("version"),
        }
        for i in top_indices
        if scores[i] > 0
    ]


async def _vector_search(
    collection: str,
    where: dict[str, Any],
    question: str,
    top_k: int,
) -> list[dict]:
    """稠密向量检索：问题转向量 → 按 where 过滤查询，集合不存在时返回空。"""
    embedding = (await get_embeddings([question]))[0]
    items = await get_vector_store().query(collection, embedding, top_k, where=where)
    if not items:
        logger.warning("Chroma collection %s not found or empty, returning empty", collection)
        return []

    chunks = []
    for item in items:
        meta = item["metadata"]
        chunks.append(
            {
                "text": item["text"],
                "score": item["score"],
                "chunk_index": meta["chunk_index"],
                "section": meta["section"],
                "source": "dense",
                "asset_id": meta.get("asset_id"),
                "version": meta.get("version"),
            }
        )
    return chunks


def build_scope_where(scope: dict[str, list[int]]) -> dict[str, Any]:
    """把检索 scope（asset_type → asset_ids）转成向量库 where 过滤。

    默认只命中最新版本快照（is_latest=True，D2）；旧版本检索由 T18 版本浏览显式传 version。
    """
    all_ids = sorted({aid for aids in scope.values() for aid in aids})
    where: dict[str, Any] = {META_IS_LATEST: True}
    if len(all_ids) == 1:
        where[META_ASSET_ID] = all_ids[0]
    else:
        where[META_ASSET_ID] = {"$in": all_ids}
    return where


def _scope_bm25_key(user_id: int, scope: dict[str, list[int]]) -> str:
    """BM25 缓存键：按 (user_id, 命中的资产 id 集合) 区分。"""
    ids = sorted({aid for aids in scope.values() for aid in aids})
    return f"{user_id}:[{','.join(map(str, ids))}]"


async def clear_bm25(user_id: int, asset_id: int) -> None:
    """清除指定资产的 BM25 缓存（重建/删除后调用，避免旧版本内容污染）。

    store_key 有两种形态：
    - 单资产 ``{user_id}:[3]``
    - 多资产 scope ``{user_id}:[1,2,3]``（_scope_bm25_key 按命中的全部资产 id 生成）

    原实现只 pop 单资产精确 key，多资产组合 key 会残留旧索引（已删简历的 chunks）。
    改为遍历该用户全部 key，按逗号拆分精确匹配 asset_id，一并删除。
    只影响 ``{user_id}:[`` 前缀的个人 key，不触碰 ``market:{collection}:[`` 公共 key。
    """
    async with _bm25_lock:
        prefix = f"{user_id}:["
        stale = [
            key
            for key in _bm25_indexes
            if key.startswith(prefix) and str(asset_id) in key[len(prefix):-1].split(",")
        ]
        for key in stale:
            _bm25_indexes.pop(key, None)


async def clear_user_bm25(user_id: int) -> None:
    """清除某用户全部 BM25 缓存（账户删除时调用，释放所有 scope 组合索引）。"""
    async with _bm25_lock:
        prefix = f"{user_id}:["
        for key in [k for k in _bm25_indexes if k.startswith(prefix)]:
            _bm25_indexes.pop(key, None)


async def hybrid_search_corpus(
    user_id: int,
    scope: dict[str, list[int]],
    question: str,
    top_k: int = 5,
    *,
    collection: str | None = None,
) -> list[dict]:
    """知识资产库检索（T7, D1/D4）：稠密 + BM25 → RRF 融合 → 返回 top_k。

    - collection 默认每用户一个（knowledge_{user_id}）；市场数据显式传
      ``market_collection_name()``（公共集合，所有用户共享）
    - scope 过滤（asset_type → asset_ids）+ is_latest 默认过滤
    - RRF 融合留在应用层，可移植（D9）
    - 公共集合的 BM25 缓存键加 ``market:{collection}:`` 前缀，与个人集合隔离
    """
    if collection is None:
        collection = knowledge_collection_name(user_id)
    where = build_scope_where(scope)
    if collection == knowledge_collection_name(user_id):
        store_key = _scope_bm25_key(user_id, scope)
    else:
        ids = sorted({aid for aids in scope.values() for aid in aids})
        store_key = f"market:{collection}:[{','.join(map(str, ids))}]"
    dense, sparse = await asyncio.gather(
        _vector_search(collection, where, question, top_k=20),
        _keyword_search(collection, where, store_key, question, top_k=20),
    )
    return _merge_results(dense, sparse, top_k)


async def hybrid_search(
    user_id: int,
    resume_id: int,
    question: str,
    top_k: int = 5,
) -> list[dict]:
    """单简历检索（hybrid_search_corpus 的特例，兼容既有调用形态）。"""
    return await hybrid_search_corpus(
        user_id, {ASSET_TYPE_RESUME: [resume_id]}, question, top_k
    )


def _merge_results(dense: list[dict], sparse: list[dict], top_k: int, k: int = 60) -> list[dict]:
    """RRF 融合：按排名而非分数合并两路结果，同一 chunk 两路都中则累加得分。

    k 为 RRF 平滑常数：k 越小排名敏感度越高（头部优势更大），默认 60 为论文原始值。

    复合键 (asset_id, chunk_index)（P2-1）：多资产 scope 检索时不同资产的
    chunk_index 会碰撞，仅用 chunk_index 会把结果错误叠加/覆盖。corpus_retrieval
    已用复合键规避，这里统一。单资产场景 asset_id 相同，行为不变。
    """
    scores: dict[tuple[int | None, int], dict] = {}
    for rank, item in enumerate(dense):
        key = (item.get("asset_id"), item["chunk_index"])
        scores[key] = {"item": item, "score": 1.0 / (k + rank + 1)}
    for rank, item in enumerate(sparse):
        key = (item.get("asset_id"), item["chunk_index"])
        if key in scores:
            scores[key]["score"] += 1.0 / (k + rank + 1)
        else:
            scores[key] = {"item": item, "score": 1.0 / (k + rank + 1)}

    ranked = sorted(scores.values(), key=lambda x: x["score"], reverse=True)
    return [x["item"] for x in ranked[:top_k]]


async def rerank(question: str, chunks: list[dict], top_k: int = 5) -> list[dict]:
    """Rerank Cross-Encoder 精排（模型由 settings.RERANK_MODEL 决定）：返回新列表，不原地修改输入 chunks"""
    if len(chunks) <= top_k:
        return [dict(c) for c in chunks]  # 返回副本，避免调用方持有同一引用

    async def _call_api():
        client = await _get_http_client()
        resp = await client.post(
            settings.RERANK_BASE_URL,
            json={
                "model": settings.RERANK_MODEL,
                "input": {
                    "query": question,
                    "documents": [c["text"][:400] for c in chunks],
                },
                "parameters": {"top_n": top_k},
            },
            headers={
                "Authorization": f"Bearer {settings.RERANK_API_KEY}",
                "Content-Type": "application/json",
            },
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()

    try:
        data = await with_retry(_call_api, fallback=None)
        if data is None:
            raise RuntimeError("Rerank API 全部重试失败")
        results = data.get("output", {}).get("results", [])
        # P0.5: HTTP 200 但 results 为空视为异常，走与 API 失败一致的降级路径
        # 否则 score_map={} → 所有 chunk rerank_score=0.0 → reject_if_low_score 误拒答
        if not results:
            logger.warning("Rerank API returned empty results, falling back to original order")
            return [{**c, "rerank_score": 0.5} for c in chunks][:top_k]
    except Exception as e:
        logger.warning("Rerank API failed: %s, falling back to original order", e)
        # H3 修复：返回带 rerank_score 的副本，不原地修改输入 chunks
        return [{**c, "rerank_score": 0.5} for c in chunks][:top_k]

    score_map: dict[int, float] = {r["index"]: r["relevance_score"] for r in results}
    scored = [{**c, "rerank_score": score_map.get(i, 0.0)} for i, c in enumerate(chunks)]

    # H3 修复：使用 sorted 返回新列表，而非对入参原地排序
    scored_sorted = sorted(scored, key=lambda c: c.get("rerank_score", 0), reverse=True)
    return scored_sorted[:top_k]


def reject_if_low_score(chunks: list[dict], threshold: float = 0.3) -> bool:
    """Rerank 后最高分低于阈值则拒答。无 rerank_score 的 chunk（未经过 rerank）不拒答。"""
    if not chunks:
        return True
    scores = [c["rerank_score"] for c in chunks if "rerank_score" in c]
    if not scores:
        return False  # 未经过 rerank，保留所有结果
    return max(scores) < threshold
