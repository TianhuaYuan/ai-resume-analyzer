"""检索与排序：Embedding 向量化 / BM25 关键词 / 混合检索(RRF) / Cross-Encoder 重排 / 拒答判定。

阶段11 从 rag_service.py 拆出：所有与"从简历里找出相关段落"相关的能力都集中于此，
是自包含、可直接单测的核心检索层。
"""
import asyncio
import logging
from typing import Any

import httpx
from rank_bm25 import BM25Okapi

from core import cache as embedding_cache
from core.config import settings
from core.rag_params import RagParams
from core.retry import with_retry
from services.rag.chunking import _tokenize
from services.rag.clients import _collection_name, get_chroma_client, get_embedding_client, with_chroma

logger = logging.getLogger(__name__)

_bm25_indexes: dict[int, tuple[BM25Okapi, list[dict]]] = {}
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
            batch_texts = uncached[batch_start:batch_start + 10]
            batch_idx = uncached_idx[batch_start:batch_start + 10]
            response = await client.embeddings.create(
                model=settings.EMBEDDING_MODEL, input=batch_texts,
            )
            for j, item in enumerate(response.data):
                idx = batch_idx[j]
                vectors[idx] = item.embedding
                await embedding_cache.set_embedding(batch_texts[j], item.embedding, resume_id)

    return vectors


async def _load_bm25_index(
    resume_id: int,
    collection_name: str | None = None,
    bm25_key: Any | None = None,
) -> bool:
    """从 Chroma 读取文档构建 BM25 索引，返回是否加载成功。

    collection_name / bm25_key 为可选项，用于参数化实验的命名空间隔离（Model C）：
    - collection_name：要读取的 Chroma 集合（默认 resume_{resume_id}）。
    - bm25_key：写入 _bm25_indexes 的键（默认 resume_id）。生产路径保持 resume_id。
    """
    name = collection_name or _collection_name(resume_id)
    store_key = bm25_key if bm25_key is not None else resume_id

    def _sync_get():
        try:
            collection = get_chroma_client().get_collection(name)
        except Exception:
            return None
        return collection.get(include=["documents", "metadatas"])

    data = await with_chroma(_sync_get)
    if data is None:
        logger.warning("Chroma collection %s not found, skip BM25 build", name)
        return False
    chunks = []
    for doc, meta in zip(data["documents"], data["metadatas"]):
        chunks.append({
            "text": doc,
            "chunk_index": meta["chunk_index"],
            "section": meta["section"],
        })
    if not chunks:
        return False
    tokenized = [_tokenize(c["text"]) for c in chunks]
    # LRU 淘汰：超过上限时移除最早的条目
    while len(_bm25_indexes) >= _BM25_MAX_SIZE:
        oldest = next(iter(_bm25_indexes))
        _bm25_indexes.pop(oldest, None)
    _bm25_indexes[store_key] = (BM25Okapi(tokenized), chunks)
    return True


async def _keyword_search(
    resume_id: int,
    question: str,
    top_k: int,
    bm25_key: Any | None = None,
    collection_name: str | None = None,
) -> list[dict]:
    """BM25 关键词检索：懒加载索引 → 分词算分 → 返回 top_k，过滤零分结果。

    bm25_key / collection_name 为可选项，用于参数化实验隔离（默认按 resume_id）。
    """
    store_key = bm25_key if bm25_key is not None else resume_id
    async with _bm25_lock:
        if store_key not in _bm25_indexes:
            if not await _load_bm25_index(resume_id, collection_name=collection_name, bm25_key=bm25_key):
                return []
        # H2 修复：将 _bm25_indexes.get() 的读取纳入锁临界区，
        # 避免与 clear_resume_vectors 的 pop 产生数据竞争
        index_data = _bm25_indexes.get(store_key)
    if index_data is None:
        return []
    index, chunks = index_data
    scores = index.get_scores(_tokenize(question))
    top_indices = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:top_k]
    return [
        {
            "text": chunks[i]["text"],
            "score": float(scores[i]),
            "chunk_index": chunks[i]["chunk_index"],
            "section": chunks[i]["section"],
            "source": "sparse",
        }
        for i in top_indices if scores[i] > 0
    ]


async def _vector_search(
    resume_id: int, question: str, top_k: int, collection_name: str | None = None,
) -> list[dict]:
    """稠密向量检索：问题转向量 → Chroma 余弦相似度查询，collection 不存在时返回空。
    collection_name 为可选项，用于参数化实验隔离（默认 resume_{resume_id}）。
    """
    embedding = (await get_embeddings([question]))[0]
    name = collection_name or _collection_name(resume_id)

    def _sync_query():
        try:
            collection = get_chroma_client().get_collection(name)
        except Exception:
            return None
        return collection.query(
            query_embeddings=[embedding],
            n_results=top_k,
            include=["documents", "metadatas", "distances"],
        )

    results = await with_chroma(_sync_query)
    if results is None:
        logger.warning("Chroma collection %s not found, returning empty", name)
        return []

    chunks = []
    for i in range(len(results["ids"][0])):
        meta = results["metadatas"][0][i]
        chunks.append({
            "text": results["documents"][0][i],
            "score": 1.0 - results["distances"][0][i],  # cosine distance 0..2 → similarity -1..1
            "chunk_index": meta["chunk_index"],
            "section": meta["section"],
            "source": "dense",
        })
    return chunks


async def hybrid_search(resume_id: int, question: str, top_k: int = 5) -> list[dict]:
    """稠密向量 + BM25 关键词 → RRF 融合 → 返回 top_k"""
    dense, sparse = await asyncio.gather(
        _vector_search(resume_id, question, top_k=20),
        _keyword_search(resume_id, question, top_k=20),
    )
    return _merge_results(dense, sparse, top_k)


async def hybrid_search_p(
    resume_id: int, question: str, p: RagParams,
    collection_name: str | None = None, bm25_key: Any | None = None,
) -> list[dict]:
    """参数化版混合检索。collection_name / bm25_key 用于参数化实验隔离（Model C）。"""
    dense, sparse = await asyncio.gather(
        _vector_search(resume_id, question, top_k=p.dense_top_k, collection_name=collection_name),
        _keyword_search(resume_id, question, top_k=p.sparse_top_k, bm25_key=bm25_key, collection_name=collection_name),
    )
    return _merge_results(dense, sparse, top_k=p.hybrid_top_k, k=p.rrf_k)


def _merge_results(dense: list[dict], sparse: list[dict], top_k: int, k: int = 60) -> list[dict]:
    """RRF 融合：按排名而非分数合并两路结果，同一 chunk 两路都中则累加得分。

    k 为 RRF 平滑常数：k 越小排名敏感度越高（头部优势更大），默认 60 为论文原始值。
    """
    scores: dict[int, dict] = {}
    for rank, item in enumerate(dense):
        key = item["chunk_index"]
        scores[key] = {"item": item, "score": 1.0 / (k + rank + 1)}
    for rank, item in enumerate(sparse):
        key = item["chunk_index"]
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
        async with httpx.AsyncClient() as client:
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
    except Exception as e:
        logger.warning("Rerank API failed: %s, falling back to original order", e)
        # H3 修复：返回带 rerank_score 的副本，不原地修改输入 chunks
        return [{**c, "rerank_score": 0.5} for c in chunks][:top_k]

    score_map: dict[int, float] = {r["index"]: r["relevance_score"] for r in results}
    scored = [{**c, "rerank_score": score_map.get(i, 0.0)} for i, c in enumerate(chunks)]

    # H3 修复：使用 sorted 返回新列表，而非对入参原地排序
    scored_sorted = sorted(scored, key=lambda c: c.get("rerank_score", 0), reverse=True)
    return scored_sorted[:top_k]


async def rerank_p(question: str, chunks: list[dict], p: RagParams) -> list[dict]:
    """参数化版 Rerank，支持可配截断长度和 top_k；返回新列表，不原地修改输入"""
    if len(chunks) <= p.rerank_final_top_k:
        return [dict(c) for c in chunks]

    trunc = p.rerank_truncation if p.rerank_truncation > 0 else 999999

    async def _call_api():
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                settings.RERANK_BASE_URL,
                json={
                    "model": settings.RERANK_MODEL,
                    "input": {
                        "query": question,
                        "documents": [c["text"][:trunc] for c in chunks],
                    },
                    "parameters": {"top_n": p.rerank_final_top_k},
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
    except Exception as e:
        logger.warning("Rerank API failed: %s, falling back to original order", e)
        # H3 修复：返回带 rerank_score 的副本，不原地修改输入 chunks
        return [{**c, "rerank_score": 0.5} for c in chunks][:p.rerank_final_top_k]

    score_map: dict[int, float] = {r["index"]: r["relevance_score"] for r in results}
    scored = [{**c, "rerank_score": score_map.get(i, 0.0)} for i, c in enumerate(chunks)]

    # H3 修复：使用 sorted 返回新列表，而非对入参原地排序
    scored_sorted = sorted(scored, key=lambda c: c.get("rerank_score", 0), reverse=True)
    return scored_sorted[:p.rerank_final_top_k]


def reject_if_low_score(chunks: list[dict], threshold: float = 0.3) -> bool:
    """Rerank 后最高分低于阈值则拒答。无 rerank_score 的 chunk（未经过 rerank）不拒答。"""
    if not chunks:
        return True
    scores = [c["rerank_score"] for c in chunks if "rerank_score" in c]
    if not scores:
        return False  # 未经过 rerank，保留所有结果
    return max(scores) < threshold
