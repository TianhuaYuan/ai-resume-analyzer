import logging
import time

from services.agentic_rag.state import AgenticRAGState
from services.rag.retrieval import hybrid_search, rerank

logger = logging.getLogger(__name__)

_DEFAULT_HYBRID_TOP_K = 20
_DEFAULT_RERANK_TOP_K = 5


def _deduplicate_chunks(chunks: list[dict]) -> list[dict]:
    seen = set()
    unique = []
    for chunk in chunks:
        key = (chunk.get("chunk_index", -1), chunk.get("text", "")[:100])
        if key not in seen:
            seen.add(key)
            unique.append(chunk)
    return unique


async def search_node(state: AgenticRAGState) -> dict:
    query = state.get("rewritten_query") or state["question"]
    resume_id = state["resume_id"]
    round_num = state.get("search_round", 0)
    supplement_queries = state.get("supplement_queries", [])

    # 阶段4 错误透传：tool_errors 是累加字段，先继承 state 中已有的，再 append 本次失败。
    tool_errors = list(state.get("tool_errors", []))

    timer_start = time.monotonic()

    queries_to_search = [query]
    if supplement_queries:
        queries_to_search.extend(supplement_queries[:3])

    all_chunks = []
    for q in queries_to_search:
        try:
            chunks = await hybrid_search(resume_id, q, top_k=_DEFAULT_HYBRID_TOP_K)
        except Exception as exc:
            # 某个检索子步骤（稠密向量 / 稀疏 BM25 融合）失败：
            # 记录而非抛出，保证其余查询仍能返回结果，实现「部分降级」而非全盘失败。
            logger.warning("search_node: hybrid_search failed for query=%r: %s", q, exc)
            tool_errors.append(
                {
                    "tool": "hybrid_search",
                    "query": q,
                    "error": str(exc)[:300],
                }
            )
            continue
        all_chunks.extend(chunks)

    unique_chunks = _deduplicate_chunks(all_chunks)

    elapsed = time.monotonic() - timer_start

    logger.info(
        "search_node: resume=%d round=%d queries=%d → %d unique chunks (%.2fs)",
        resume_id,
        round_num,
        len(queries_to_search),
        len(unique_chunks),
        elapsed,
    )

    trace = dict(state.get("trace", {}))
    trace["search"] = {
        "elapsed_ms": int(elapsed * 1000),
        "query": query,
        "supplement_queries": supplement_queries,
        "chunk_count": len(unique_chunks),
        "round": round_num,
    }

    return {
        "chunks": unique_chunks,
        "search_round": round_num + 1,
        "tool_errors": tool_errors,
        "trace": trace,
    }


async def rerank_node(state: AgenticRAGState) -> dict:
    chunks = state.get("chunks", [])
    query = state.get("rewritten_query") or state["question"]

    # 阶段4 错误透传：继承 search_node 已记录的 tool_errors。
    tool_errors = list(state.get("tool_errors", []))

    if not chunks:
        logger.warning("rerank_node: no chunks to rerank")
        trace = dict(state.get("trace", {}))
        trace["rerank"] = {"elapsed_ms": 0, "input_count": 0, "output_count": 0}
        return {"chunks": [], "tool_errors": tool_errors, "trace": trace}

    timer_start = time.monotonic()
    try:
        reranked = await rerank(query, chunks, top_k=_DEFAULT_RERANK_TOP_K)
    except Exception as exc:
        # rerank 失败：降级为原始顺序（不重排），并记录工具错误，让下游感知「精排缺失」。
        logger.warning("rerank_node: rerank failed, falling back to original order: %s", exc)
        tool_errors.append(
            {
                "tool": "rerank",
                "query": query,
                "error": str(exc)[:300],
            }
        )
        reranked = chunks
    elapsed = time.monotonic() - timer_start

    logger.info(
        "rerank_node: %d → %d chunks (%.2fs)",
        len(chunks),
        len(reranked),
        elapsed,
    )

    trace = dict(state.get("trace", {}))
    trace["rerank"] = {
        "elapsed_ms": int(elapsed * 1000),
        "input_count": len(chunks),
        "output_count": len(reranked),
    }

    return {
        "chunks": reranked,
        "tool_errors": tool_errors,
        "trace": trace,
    }
