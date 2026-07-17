from typing import TypedDict


class AgenticRAGState(TypedDict):
    question: str
    resume_id: int
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
    reflection_result: str
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
