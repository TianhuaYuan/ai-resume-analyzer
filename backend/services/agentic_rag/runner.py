"""agentic RAG 统一入口（T11, D5）。

``run_answer_from_index(user_id, scope, question)`` 是图对外唯一入口：
- ReAct agent 的 ``answer_from_index`` 工具（T12）调用它
- 经典 QA（api/qa.py ``_run_agentic_rag``）也收敛到这里，避免重复实现

图内部节点负责"怎么检索 + 要不要反思"（route deep|fast / search / reflexion），
调用方负责"检索哪些资产"（scope）。
"""

import logging
import uuid

logger = logging.getLogger(__name__)

_AGENTIC_GRAPH = None


def get_agentic_graph():
    """懒加载并缓存编译好的 Agentic RAG 图（避免模块导入期重依赖）。"""
    global _AGENTIC_GRAPH
    if _AGENTIC_GRAPH is None:
        from services.agentic_rag.graph import create_agentic_rag_graph

        _AGENTIC_GRAPH = create_agentic_rag_graph()
    return _AGENTIC_GRAPH


def _build_initial_state(
    user_id: int,
    scope: dict[str, list[int]],
    question: str,
) -> dict:
    return {
        "question": question,
        # legacy：兼容字段（标准图/工具保留）
        "resume_id": 0,
        "user_id": user_id,
        "scope": scope,
        "filters": {"version": "latest"},
        "scope_expansion": [],
        "rewritten_query": "",
        "route_decision": "search",
        "chunks": [],
        "search_round": 0,
        "answer": "",
        "sources": [],
        "eval_score": 0.0,
        "eval_feedback": "",
        "should_retry": False,
        "completeness_score": 0.0,
        "accuracy_score": 0.0,
        "source_credibility_score": 0.0,
        "eval_forced": False,
        "reflection_result": "",
        "missing_info": [],
        "supplement_queries": [],
        "reflection_round": 0,
        "final_answer": "",
        "final_sources": [],
        "trace": {},
        "tool_errors": [],
    }


async def run_answer_from_index(
    *,
    user_id: int,
    scope: dict[str, list[int]],
    question: str,
) -> dict:
    """按 scope 跑 agentic RAG 图，返回结构化结果。

    Returns:
        {
            "answer": str,                  # 最终答案
            "sources": list[dict],          # per-asset 来源（含 asset_id/asset_type/version）
            "eval_score": float,            # 综合评分（完整性40/准确性40/来源20）
            "reflection_round": int,        # 反思轮数（0 表示未反思）
            "tool_errors": list[dict],      # 部分降级记录
            "trace": dict,                  # 节点耗时/决策轨迹
        }
    """
    graph = get_agentic_graph()
    initial_state = _build_initial_state(user_id, scope, question)
    result = await graph.ainvoke(
        initial_state,
        config={"configurable": {"thread_id": str(uuid.uuid4())}},
    )
    return {
        "answer": result.get("final_answer") or result.get("answer", ""),
        "sources": result.get("sources", []) or [],
        "eval_score": result.get("eval_score", 0.0),
        "reflection_round": result.get("reflection_round", 0),
        "tool_errors": result.get("tool_errors", []) or [],
        "trace": result.get("trace", {}) or {},
        # P2-2：透传反思识别的"当前范围缺哪类资产"信号（resume/jd/interview/note）。
        # 原实现 scope_expansion 是死信号——反思产出了但无消费方。透传后调用方
        # （answer_from_index 工具 / 经典 QA）可据此提示用户"回答可能缺 X 资产"，
        # 或由上层决定是否补充 scope 重跑。
        "scope_expansion": result.get("scope_expansion", []) or [],
    }
