"""Agentic RAG 工作流（StateGraph 组装）。

阶段11 合并：原 `mcp_graph.py` 的节点/边已并入本文件，两种模式现在同处一模块：
- `create_agentic_rag_graph()`    标准模式（直连：search/rerank/generate 节点）。
                                  这是稳定导入点（api/qa.py 的 /ask 路由与阶段7 懒导入都依赖它）。
- `create_mcp_agentic_rag_graph()` MCP 模式（mcp_search/mcp_rerank/mcp_generate 节点）。

合并保留：所有节点、条件边、Reflexion 循环（≤2 轮）、阶段4 加的 self-reflection
节点与 degraded 路由、阶段2 加的 mcp 节点。两图共享 direct_answer_node /
output_node / _route_after_evaluate（逻辑一致）。
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

# MCP 模式专属节点名（与标准模式的 search/rerank/generate 区分，便于路由与调试）
MCP_SEARCH_NODE = "mcp_search"
MCP_RERANK_NODE = "mcp_rerank"
MCP_GENERATE_NODE = "mcp_generate"


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
    """评估后路由（标准/MCP 共用）：分数过低进入 Self-Reflection（Reflexion ≤2 轮），否则输出。"""
    should_retry = state.get("should_retry", False)
    search_round = state.get("search_round", 0)

    # search_round 在 search_node 中是先读后加 1，所以：
    # 第1轮搜索后 search_round=1，第2轮搜索后 search_round=2
    # _EVAL_MAX_RETRIES=2 表示最多允许 2 轮搜索，所以用 < 而非 <=
    if should_retry and search_round < _EVAL_MAX_RETRIES:
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

    标准模式和 MCP 模式的唯一区别在于 search/rerank/generate 节点和对应的路由函数，
    其余结构完全相同。此函数消除重复的图构建代码。
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
# MCP 模式路由
# ─────────────────────────────────────────────────────────────
def _route_after_route_mcp(state: AgenticRAGState) -> str:
    """MCP 模式：ROUTE 后进入 MCP_SEARCH 或 DIRECT_ANSWER。"""
    decision = state.get("route_decision", "search")
    logger.info("_route_after_route_mcp: %s", decision)
    if decision == "direct_answer":
        return DIRECT_ANSWER_NODE
    return MCP_SEARCH_NODE


def _route_after_reflection_mcp(state: AgenticRAGState) -> str:
    """MCP 模式：反思后回到 MCP_SEARCH 补充检索。"""
    logger.info("_route_after_reflection_mcp: %d supplement queries", len(state.get("supplement_queries", [])))
    return MCP_SEARCH_NODE


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


def create_mcp_agentic_rag_graph(checkpointer=None):
    """MCP 模式图：经 MCP 客户端调用（mcp_search/mcp_rerank/mcp_generate 节点）。"""
    from services.agentic_rag.mcp_nodes import mcp_generate_node, mcp_rerank_node, mcp_search_node

    compiled = _build_rag_graph(
        search_node_fn=mcp_search_node,
        rerank_node_fn=mcp_rerank_node,
        generate_node_fn=mcp_generate_node,
        route_after_route_fn=_route_after_route_mcp,
        route_after_reflection_fn=_route_after_reflection_mcp,
        search_node_name=MCP_SEARCH_NODE,
        rerank_node_name=MCP_RERANK_NODE,
        generate_node_name=MCP_GENERATE_NODE,
        checkpointer=checkpointer,
    )
    logger.info("mcp_agentic_rag graph compiled successfully")
    return compiled
