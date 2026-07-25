import logging
import time
from typing import Any

from core.config import settings
from mcp_client.tools import mcp_search, mcp_rerank, mcp_generate
from services.agentic_rag.state import AgenticRAGState
from services.agentic_rag.generate import _extract_sources
from services.rag.retrieval import reject_if_low_score

logger = logging.getLogger(__name__)


def _parse_mcp_list_result(raw: Any, error_context: str) -> list[dict]:
    """解析 MCP 工具返回的列表结果，统一处理 dict/list/error 三种情况。"""
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict):
        if "error" in raw:
            logger.error("%s: %s", error_context, raw["error"])
            return []
        return raw.get("results", [])
    return []


def _parse_mcp_generate_result(raw: Any) -> tuple[str, list[dict], bool]:
    """解析 MCP generate 工具返回的结果，返回 (answer, sources, rejected)。"""
    if isinstance(raw, dict) and "error" not in raw:
        return (
            raw.get("answer", "服务暂时不可用，请稍后重试。"),
            raw.get("sources", []),
            raw.get("rejected", False),
        )
    return "服务暂时不可用，请稍后重试。", [], True


async def mcp_search_node(state: AgenticRAGState) -> dict:
    query = state.get("rewritten_query") or state["question"]
    resume_id = state["resume_id"]
    round_num = state.get("search_round", 0)

    timer_start = time.monotonic()
    raw_results = await mcp_search(query, resume_id, top_k=settings.DEFAULT_HYBRID_TOP_K)
    chunks = _parse_mcp_list_result(raw_results, "mcp_search_node: MCP error")
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

    tool_errors = list(state.get("tool_errors", []))
    if not chunks:
        tool_errors.append({
            "tool": "mcp_search",
            "query": query,
            "error": f"MCP search returned empty results for query: {query}",
        })

    return {
        "chunks": chunks,
        "search_round": round_num + 1,
        "trace": trace,
        "tool_errors": tool_errors,
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
    raw_results = await mcp_rerank(query, chunks, top_k=settings.DEFAULT_RERANK_TOP_K)

    reranked = _parse_mcp_list_result(raw_results, "mcp_rerank_node: MCP error")
    if not reranked:
        # 降级：保留原始顺序，给出保底分数（创建新 dict，不原地修改 state 中的 chunks）
        reranked = [
            {**c, "rerank_score": c.get("rerank_score", 0.5)}
            for c in chunks[:settings.DEFAULT_RERANK_TOP_K]
        ]

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
    tool_errors = list(state.get("tool_errors", []))

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
            "tool_errors": tool_errors,
            "trace": trace,
        }

    raw_result = await mcp_generate(query, chunks, state["resume_id"])
    answer, mcp_sources, rejected = _parse_mcp_generate_result(raw_result)

    if rejected:
        tool_errors.append({
            "tool": "mcp_generate",
            "query": query,
            "error": "MCP generate failed or returned error",
        })

    sources = mcp_sources if mcp_sources else _extract_sources(chunks)
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
        "tool_errors": tool_errors,
        "trace": trace,
    }
