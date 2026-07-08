import logging
import time

from services.agentic_rag.state import AgenticRAGState
from services.rag_service import hybrid_search, rerank

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

    timer_start = time.monotonic()

    queries_to_search = [query]
    if supplement_queries:
        queries_to_search.extend(supplement_queries[:3])

    all_chunks = []
    for q in queries_to_search:
        chunks = await hybrid_search(resume_id, q, top_k=_DEFAULT_HYBRID_TOP_K)
        all_chunks.extend(chunks)

    unique_chunks = _deduplicate_chunks(all_chunks)

    elapsed = time.monotonic() - timer_start

    logger.info(
        "search_node: resume=%d round=%d queries=%d → %d unique chunks (%.2fs)",
        resume_id, round_num, len(queries_to_search), len(unique_chunks), elapsed,
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
        "trace": trace,
    }


async def rerank_node(state: AgenticRAGState) -> dict:
    chunks = state.get("chunks", [])
    query = state.get("rewritten_query") or state["question"]

    if not chunks:
        logger.warning("rerank_node: no chunks to rerank")
        trace = dict(state.get("trace", {}))
        trace["rerank"] = {"elapsed_ms": 0, "input_count": 0, "output_count": 0}
        return {"chunks": [], "trace": trace}

    timer_start = time.monotonic()
    reranked = await rerank(query, chunks, top_k=_DEFAULT_RERANK_TOP_K)
    elapsed = time.monotonic() - timer_start

    logger.info(
        "rerank_node: %d → %d chunks (%.2fs)",
        len(chunks), len(reranked), elapsed,
    )

    trace = dict(state.get("trace", {}))
    trace["rerank"] = {
        "elapsed_ms": int(elapsed * 1000),
        "input_count": len(chunks),
        "output_count": len(reranked),
    }

    return {
        "chunks": reranked,
        "trace": trace,
    }
