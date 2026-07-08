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
    SELF_REFLECTION_NODE,
    OUTPUT_NODE,
)
from services.agentic_rag.rewrite import rewrite_node, route_node
from services.agentic_rag.search import search_node, rerank_node
from services.agentic_rag.generate import generate_node, evaluate_node
from services.agentic_rag.reflection import self_reflection_node

logger = logging.getLogger(__name__)

DIRECT_ANSWER_NODE = "direct_answer"
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
        "reflection_rounds": state.get("reflection_round", 0),
    }

    logger.info(
        "output_node: answer=%d chars, sources=%d, rounds=%d, eval=%.2f, reflections=%d",
        len(answer), len(final_sources), state.get("search_round", 0),
        state.get("eval_score", 0.0), state.get("reflection_round", 0),
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
    return SEARCH_NODE


def _route_after_evaluate(state: AgenticRAGState) -> str:
    should_retry = state.get("should_retry", False)
    search_round = state.get("search_round", 0)

    if should_retry and search_round <= 2:
        logger.info("_route_after_evaluate: reflexion (round=%d)", search_round)
        return SELF_REFLECTION_NODE

    logger.info("_route_after_evaluate: output (retry=%s, round=%d)", should_retry, search_round)
    return OUTPUT_NODE


def _route_after_reflection(state: AgenticRAGState) -> str:
    supplement_queries = state.get("supplement_queries", [])
    logger.info("_route_after_reflection: %d supplement queries", len(supplement_queries))
    return SEARCH_NODE


def create_agentic_rag_graph(checkpointer=None):
    if checkpointer is None:
        checkpointer = MemorySaver()

    graph = StateGraph(AgenticRAGState)

    graph.add_node(REWRITE_NODE, rewrite_node)
    graph.add_node(ROUTE_NODE, route_node)
    graph.add_node(SEARCH_NODE, search_node)
    graph.add_node(RERANK_NODE, rerank_node)
    graph.add_node(GENERATE_NODE, generate_node)
    graph.add_node(EVALUATE_NODE, evaluate_node)
    graph.add_node(SELF_REFLECTION_NODE, self_reflection_node)
    graph.add_node(DIRECT_ANSWER_NODE, direct_answer_node)
    graph.add_node(OUTPUT_NODE, output_node)

    graph.add_edge(START, REWRITE_NODE)
    graph.add_edge(REWRITE_NODE, ROUTE_NODE)

    graph.add_conditional_edges(
        ROUTE_NODE,
        _route_after_route,
        {
            SEARCH_NODE: SEARCH_NODE,
            DIRECT_ANSWER_NODE: DIRECT_ANSWER_NODE,
        },
    )

    graph.add_edge(SEARCH_NODE, RERANK_NODE)
    graph.add_edge(RERANK_NODE, GENERATE_NODE)
    graph.add_edge(GENERATE_NODE, EVALUATE_NODE)

    graph.add_conditional_edges(
        EVALUATE_NODE,
        _route_after_evaluate,
        {
            SELF_REFLECTION_NODE: SELF_REFLECTION_NODE,
            OUTPUT_NODE: OUTPUT_NODE,
        },
    )

    graph.add_conditional_edges(
        SELF_REFLECTION_NODE,
        _route_after_reflection,
        {
            SEARCH_NODE: SEARCH_NODE,
        },
    )

    graph.add_edge(DIRECT_ANSWER_NODE, OUTPUT_NODE)
    graph.add_edge(OUTPUT_NODE, END)

    compiled = graph.compile(checkpointer=checkpointer)
    logger.info("agentic_rag graph compiled successfully (with Reflexion)")
    return compiled
