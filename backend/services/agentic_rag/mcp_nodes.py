import logging
import time

from mcp_client.tools import mcp_search, mcp_rerank, mcp_generate
from services.agentic_rag.state import AgenticRAGState
from services.agentic_rag.generate import _extract_sources
from services.rag.pipeline import reject_if_low_score

logger = logging.getLogger(__name__)

_DEFAULT_HYBRID_TOP_K = 20
_DEFAULT_RERANK_TOP_K = 5


async def mcp_search_node(state: AgenticRAGState) -> dict:
    query = state.get("rewritten_query") or state["question"]
    resume_id = state["resume_id"]
    round_num = state.get("search_round", 0)

    timer_start = time.monotonic()
    raw_results = await mcp_search(query, resume_id, top_k=_DEFAULT_HYBRID_TOP_K)

    if isinstance(raw_results, list):
        chunks = raw_results
    elif isinstance(raw_results, dict):
        if "error" in raw_results:
            logger.error("mcp_search_node: MCP error: %s", raw_results["error"])
            chunks = []
        else:
            chunks = raw_results.get("results", [])
    else:
        chunks = []

    elapsed = time.monotonic() - timer_start

    logger.info(
        "mcp_search_node: resume=%d round=%d query='%s' → %d chunks (%.2fs)",
        resume_id,
        round_num,
        query[:50],
        len(chunks),
        elapsed,
    )

    trace = dict(state.get("trace", {}))
    trace["search"] = {
        "elapsed_ms": int(elapsed * 1000),
        "query": query,
        "chunk_count": len(chunks),
        "round": round_num,
        "method": "mcp",
    }

    return {
        "chunks": chunks,
        "search_round": round_num + 1,
        "trace": trace,
    }


async def mcp_rerank_node(state: AgenticRAGState) -> dict:
    chunks = state.get("chunks", [])
    query = state.get("rewritten_query") or state["question"]

    if not chunks:
        logger.warning("mcp_rerank_node: no chunks to rerank")
        trace = dict(state.get("trace", {}))
        trace["rerank"] = {"elapsed_ms": 0, "input_count": 0, "output_count": 0, "method": "mcp"}
        return {"chunks": [], "trace": trace}

    timer_start = time.monotonic()
    raw_results = await mcp_rerank(query, chunks, top_k=_DEFAULT_RERANK_TOP_K)

    if isinstance(raw_results, list):
        reranked = raw_results
    elif isinstance(raw_results, dict):
        if "error" in raw_results:
            logger.error("mcp_rerank_node: MCP error: %s", raw_results["error"])
            for c in chunks:
                c.setdefault("rerank_score", 0.5)
            reranked = chunks[:_DEFAULT_RERANK_TOP_K]
        else:
            reranked = raw_results.get("results", chunks[:_DEFAULT_RERANK_TOP_K])
    else:
        reranked = chunks[:_DEFAULT_RERANK_TOP_K]

    elapsed = time.monotonic() - timer_start

    logger.info(
        "mcp_rerank_node: %d → %d chunks (%.2fs)",
        len(chunks),
        len(reranked),
        elapsed,
    )

    trace = dict(state.get("trace", {}))
    trace["rerank"] = {
        "elapsed_ms": int(elapsed * 1000),
        "input_count": len(chunks),
        "output_count": len(reranked),
        "method": "mcp",
    }

    return {
        "chunks": reranked,
        "trace": trace,
    }


async def mcp_generate_node(state: AgenticRAGState) -> dict:
    chunks = state.get("chunks", [])
    query = state.get("rewritten_query") or state["question"]

    timer_start = time.monotonic()

    if not chunks or reject_if_low_score(chunks):
        elapsed = time.monotonic() - timer_start
        logger.info("mcp_generate_node: no valid chunks, returning rejection")
        trace = dict(state.get("trace", {}))
        trace["generate"] = {
            "elapsed_ms": int(elapsed * 1000),
            "chunk_count": 0,
            "rejected": True,
            "method": "mcp",
        }
        return {
            "answer": "抱歉，简历中未提及该信息。",
            "sources": [],
            "trace": trace,
        }

    raw_result = await mcp_generate(query, chunks, state["resume_id"])

    if isinstance(raw_result, dict) and "error" not in raw_result:
        answer = raw_result.get("answer", "服务暂时不可用，请稍后重试。")
        mcp_sources = raw_result.get("sources", [])
        rejected = raw_result.get("rejected", False)
    else:
        answer = "服务暂时不可用，请稍后重试。"
        mcp_sources = []
        rejected = True

    if mcp_sources:
        sources = mcp_sources
    else:
        sources = _extract_sources(chunks)

    elapsed = time.monotonic() - timer_start

    logger.info(
        "mcp_generate_node: query='%s' → %d chars, %d sources (%.2fs)",
        query[:50],
        len(answer),
        len(chunks),
        elapsed,
    )

    trace = dict(state.get("trace", {}))
    trace["generate"] = {
        "elapsed_ms": int(elapsed * 1000),
        "chunk_count": len(chunks),
        "answer_length": len(answer),
        "rejected": rejected,
        "method": "mcp",
    }

    return {
        "answer": answer,
        "sources": sources,
        "trace": trace,
    }
