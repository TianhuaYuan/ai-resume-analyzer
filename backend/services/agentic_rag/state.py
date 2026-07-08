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


REWRITE_NODE = "rewrite"
ROUTE_NODE = "route"
SEARCH_NODE = "search"
RERANK_NODE = "rerank"
GENERATE_NODE = "generate"
EVALUATE_NODE = "evaluate"
SELF_REFLECTION_NODE = "self_reflection"
OUTPUT_NODE = "output"
