"""Agentic RAG 工作流（StateGraph 组装，标准模式）。

`create_agentic_rag_graph()`：直连 search/rerank/generate 节点的标准模式，
是稳定导入点（api/qa.py 的 /ask 路由依赖它）。包含完整节点、条件边、
Reflexion 循环（≤2 轮）、self-reflection 节点与 degraded 路由。

注：MCP 版图（原 mcp_graph/mcp_nodes）已在 T14 退役删除，生产走
mcp_server/tools/answer.py 的 answer_from_index 原子工具。
"""

import json
import logging
from typing import Any, Callable

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from services.agentic_rag.generate import evaluate_node, _EVAL_MAX_RETRIES
from services.agentic_rag.reflection import self_reflection_node
from services.agentic_rag.rewrite import rewrite_node, route_node
from services.agentic_rag.state import (
    OUTPUT_NODE,
    REWRITE_NODE,
    ROUTE_NODE,
    SELF_REFLECTION_NODE,
    EVALUATE_NODE,
    AgenticRAGState,
)

logger = logging.getLogger(__name__)

# 共享常量
DIRECT_ANSWER_NODE = "direct_answer"
_DIRECT_ANSWER_REPLY = "你好！我是简历分析助手，请问有什么关于简历的问题我可以帮你解答？"

# ─────────────────────────────────────────────────────────────
# 共享节点
# ─────────────────────────────────────────────────────────────
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
        len(answer),
        len(final_sources),
        state.get("search_round", 0),
        state.get("eval_score", 0.0),
        state.get("reflection_round", 0),
    )

    return {
        "final_answer": answer,
        "final_sources": final_sources,
        "trace": trace,
    }


# ─────────────────────────────────────────────────────────────
# 共享路由函数
# ─────────────────────────────────────────────────────────────
def _route_after_evaluate(state: AgenticRAGState) -> str:
    """评估后路由（标准/MCP 共用）：分数过低进入 Self-Reflection（Reflexion ≤2 轮），否则输出。

    P0.3 修复：原 `search_round < _EVAL_MAX_RETRIES` 导致第2轮搜索后无法反思，
    实际只跑1轮 Reflexion。改为 `<=` 后流程为：
      - 第1轮 search→round=1，evaluate 评估，should_retry=True → 反思1
      - 第2轮 search→round=2，evaluate 评估，should_retry=True → 反思2
      - 第3轮 search→round=3，evaluate_node 中 `search_round > _EVAL_MAX_RETRIES`
        强制 should_retry=False → output
    真正实现「≤2 轮 Reflexion」语义。
    """
    should_retry = state.get("should_retry", False)
    search_round = state.get("search_round", 0)

    if should_retry and search_round <= _EVAL_MAX_RETRIES:
        logger.info("_route_after_evaluate: reflexion (round=%d)", search_round)
        return SELF_REFLECTION_NODE

    logger.info("_route_after_evaluate: output (retry=%s, round=%d)", should_retry, search_round)
    return OUTPUT_NODE


# ─────────────────────────────────────────────────────────────
# 图构建辅助函数
# ─────────────────────────────────────────────────────────────
def _build_rag_graph(
    search_node_fn: Callable,
    rerank_node_fn: Callable,
    generate_node_fn: Callable,
    route_after_route_fn: Callable,
    route_after_reflection_fn: Callable,
    search_node_name: str,
    rerank_node_name: str,
    generate_node_name: str,
    checkpointer: Any = None,
) -> Any:
    """构建 RAG 图的共享逻辑。

    通过注入 search/rerank/generate 节点函数与路由函数，消除重复的图构建代码。
    """
    if checkpointer is None:
        checkpointer = MemorySaver()

    graph = StateGraph(AgenticRAGState)

    # 共享节点
    graph.add_node(REWRITE_NODE, rewrite_node)
    graph.add_node(ROUTE_NODE, route_node)
    graph.add_node(EVALUATE_NODE, evaluate_node)
    graph.add_node(SELF_REFLECTION_NODE, self_reflection_node)
    graph.add_node(DIRECT_ANSWER_NODE, direct_answer_node)
    graph.add_node(OUTPUT_NODE, output_node)

    # 模式特定节点
    graph.add_node(search_node_name, search_node_fn)
    graph.add_node(rerank_node_name, rerank_node_fn)
    graph.add_node(generate_node_name, generate_node_fn)

    # 共享边
    graph.add_edge(START, REWRITE_NODE)
    graph.add_edge(REWRITE_NODE, ROUTE_NODE)

    graph.add_conditional_edges(
        ROUTE_NODE,
        route_after_route_fn,
        {
            search_node_name: search_node_name,
            DIRECT_ANSWER_NODE: DIRECT_ANSWER_NODE,
        },
    )

    graph.add_edge(search_node_name, rerank_node_name)
    graph.add_edge(rerank_node_name, generate_node_name)
    graph.add_edge(generate_node_name, EVALUATE_NODE)

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
        route_after_reflection_fn,
        {
            search_node_name: search_node_name,
        },
    )

    graph.add_edge(DIRECT_ANSWER_NODE, OUTPUT_NODE)
    graph.add_edge(OUTPUT_NODE, END)

    return graph.compile(checkpointer=checkpointer)


# ─────────────────────────────────────────────────────────────
# 标准模式路由
# ─────────────────────────────────────────────────────────────
def _route_after_route_standard(state: AgenticRAGState) -> str:
    """标准模式：ROUTE 后进入 SEARCH 或 DIRECT_ANSWER。"""
    decision = state.get("route_decision", "search")
    logger.info("_route_after_route: %s", decision)
    if decision == "direct_answer":
        return DIRECT_ANSWER_NODE
    return "search"


def _route_after_reflection_standard(state: AgenticRAGState) -> str:
    """标准模式：反思后回到 SEARCH 补充检索。"""
    logger.info("_route_after_reflection: %d supplement queries", len(state.get("supplement_queries", [])))
    return "search"


# ─────────────────────────────────────────────────────────────
# 公共 API
# ─────────────────────────────────────────────────────────────
def create_agentic_rag_graph(checkpointer=None):
    """标准模式图：直连（search/rerank/generate 节点）。"""
    from services.agentic_rag.search import rerank_node, search_node
    from services.agentic_rag.generate import generate_node

    compiled = _build_rag_graph(
        search_node_fn=search_node,
        rerank_node_fn=rerank_node,
        generate_node_fn=generate_node,
        route_after_route_fn=_route_after_route_standard,
        route_after_reflection_fn=_route_after_reflection_standard,
        search_node_name="search",
        rerank_node_name="rerank",
        generate_node_name="generate",
        checkpointer=checkpointer,
    )
    logger.info("agentic_rag graph compiled successfully (with Reflexion)")
    return compiled


