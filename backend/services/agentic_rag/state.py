from typing import TypedDict


class AgenticRAGState(TypedDict):
    question: str
    resume_id: int  # legacy：单简历模式（T9 过渡期保留）
    user_id: int
    # T9 泛化：检索 scope（asset_type → asset_ids）+ 过滤条件（默认 version=latest）
    scope: dict[str, list[int]]
    filters: dict
    # T10 反思：识别"当前 scope 缺哪类资产"时写入，供图扩展 scope 或返回 agent
    scope_expansion: list[str]
    rewritten_query: str
    route_decision: str  # "search" | "direct_answer"
    chunks: list[dict]
    search_round: int
    answer: str
    sources: list[dict]
    eval_score: float
    eval_feedback: str
    should_retry: bool
    completeness_score: float
    accuracy_score: float
    source_credibility_score: float
    # evaluate_node 是否因 max_retries 强制放行（返回 0.5 假分数）。
    # True = 未真正评估，直接给保底分放行；False = 真实评估或拒绝。
    # 下游可据此区分「真实 0.5 分」和「没评估直接放行」。
    eval_forced: bool
    reflection_result: str
    # D2 失败分类定向恢复（借鉴 tau-bench）：反思节点判定的失败类型 + 归因，
    # 写入 state（LangGraph channel）供追踪/下游读取；侧信道另供 react_agent.loop 使用。
    fault_type: str
    fault_assignment: str
    missing_info: list[str]
    supplement_queries: list[str]
    reflection_round: int
    final_answer: str
    final_sources: list[str]
    trace: dict
    # 阶段4 错误透传：记录检索/重排等子步骤中失败的「工具」及错误摘要。
    # 形如 [{"tool": "hybrid_search", "query": "...", "error": "..."}, ...]
    # 空列表表示全程无失败；非空时下游生成节点据此注入降级说明，API 据此置 degraded。
    # 注意：这是累加字段，由各节点在 state 已有 tool_errors 基础上 append，不覆盖。
    tool_errors: list[dict]


REWRITE_NODE = "rewrite"
ROUTE_NODE = "route"
SEARCH_NODE = "search"
RERANK_NODE = "rerank"
GENERATE_NODE = "generate"
EVALUATE_NODE = "evaluate"
SELF_REFLECTION_NODE = "self_reflection"
OUTPUT_NODE = "output"
