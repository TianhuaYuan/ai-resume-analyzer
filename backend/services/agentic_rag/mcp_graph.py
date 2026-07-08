import json
import logging

from langgraph.graph import StateGraph, END, START
from langgraph.checkpoint.memory import MemorySaver

from services.agentic_rag.state import (
    AgenticRAGState,
    REWRITE_NODE,
    ROUTE_NODE,
    SEARCH_NODE,
    RERANK_NODE,
    GENERATE_NODE,
    EVALUATE_NODE,
    OUTPUT_NODE,
)
from services.agentic_rag.rewrite import rewrite_node, route_node
from services.agentic_rag.mcp_nodes import mcp_search_node, mcp_rerank_node, mcp_generate_node
from services.agentic_rag.generate import evaluate_node

logger = logging.getLogger(__name__)

DIRECT_ANSWER_NODE = "direct_answer"
MCP_SEARCH_NODE = "mcp_search"
MCP_RERANK_NODE = "mcp_rerank"
MCP_GENERATE_NODE = "mcp_generate"
_DIRECT_ANSWER_REPLY = "你好！我是简历分析助手，请问有什么关于简历的问题我可以帮你解答？"


async def direct_answer_node(state: AgenticRAGState) -> dict:
    logger.info("direct_answer_node: returning template greeting")
    trace = dict(state.get("trace", {}))
    trace["direct_answer"] = {"elapsed_ms": 0, "template": True}
    return {
        "answer": _DIRECT_ANSWER_REPLY,
        "sources": [],
        "trace": trace,
    }


async def output_node(state: AgenticRAGState) -> dict:
    answer = state.get("answer", "")
    sources = state.get("sources", [])
    final_sources = [json.dumps(s, ensure_ascii=False) for s in sources]

    trace = dict(state.get("trace", {}))
    trace["output"] = {
        "answer_length": len(answer),
        "source_count": len(final_sources),
        "search_rounds": state.get("search_round", 0),
        "eval_score": state.get("eval_score", 0.0),
    }

    logger.info(
        "output_node: answer=%d chars, sources=%d, rounds=%d, eval=%.2f",
        len(answer), len(final_sources), state.get("search_round", 0), state.get("eval_score", 0.0),
    )

    return {
        "final_answer": answer,
        "final_sources": final_sources,
        "trace": trace,
    }


def _route_after_route(state: AgenticRAGState) -> str:
    decision = state.get("route_decision", "search")
    logger.info("_route_after_route: %s", decision)
    if decision == "direct_answer":
        return DIRECT_ANSWER_NODE
    return MCP_SEARCH_NODE


def _route_after_evaluate(state: AgenticRAGState) -> str:
    should_retry = state.get("should_retry", False)
    search_round = state.get("search_round", 0)

    if should_retry and search_round <= 2:
        logger.info("_route_after_evaluate: retry (round=%d)", search_round)
        return MCP_SEARCH_NODE

    logger.info("_route_after_evaluate: output (retry=%s, round=%d)", should_retry, search_round)
    return OUTPUT_NODE


def create_mcp_agentic_rag_graph(checkpointer=None):
    if checkpointer is None:
        checkpointer = MemorySaver()

    graph = StateGraph(AgenticRAGState)

    graph.add_node(REWRITE_NODE, rewrite_node)
    graph.add_node(ROUTE_NODE, route_node)
    graph.add_node(MCP_SEARCH_NODE, mcp_search_node)
    graph.add_node(MCP_RERANK_NODE, mcp_rerank_node)
    graph.add_node(MCP_GENERATE_NODE, mcp_generate_node)
    graph.add_node(EVALUATE_NODE, evaluate_node)
    graph.add_node(DIRECT_ANSWER_NODE, direct_answer_node)
    graph.add_node(OUTPUT_NODE, output_node)

    graph.add_edge(START, REWRITE_NODE)
    graph.add_edge(REWRITE_NODE, ROUTE_NODE)

    graph.add_conditional_edges(
        ROUTE_NODE,
        _route_after_route,
        {
            MCP_SEARCH_NODE: MCP_SEARCH_NODE,
            DIRECT_ANSWER_NODE: DIRECT_ANSWER_NODE,
        },
    )

    graph.add_edge(MCP_SEARCH_NODE, MCP_RERANK_NODE)
    graph.add_edge(MCP_RERANK_NODE, MCP_GENERATE_NODE)
    graph.add_edge(MCP_GENERATE_NODE, EVALUATE_NODE)

    graph.add_conditional_edges(
        EVALUATE_NODE,
        _route_after_evaluate,
        {
            MCP_SEARCH_NODE: MCP_SEARCH_NODE,
            OUTPUT_NODE: OUTPUT_NODE,
        },
    )

    graph.add_edge(DIRECT_ANSWER_NODE, OUTPUT_NODE)
    graph.add_edge(OUTPUT_NODE, END)

    compiled = graph.compile(checkpointer=checkpointer)
    logger.info("mcp_agentic_rag graph compiled successfully")
    return compiled
