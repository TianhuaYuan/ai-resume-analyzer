import logging
import time

from core.config import settings
from core.retry import with_retry
from services.rag.pipeline import rewrite_query, llm_generate
from services.agentic_rag.state import AgenticRAGState

logger = logging.getLogger(__name__)


async def rewrite_node(state: AgenticRAGState) -> dict:
    question = state["question"]
    timer_start = time.monotonic()

    try:
        rewritten = await rewrite_query(
            question,
            model=settings.JUDGE_MODEL if settings.JUDGE_ENABLED else None,
            user_id=state.get("user_id"),
        )
    except Exception:
        logger.warning("rewrite_node: rewrite_query failed, falling back to original")
        rewritten = question

    rewritten = rewritten or question

    elapsed = time.monotonic() - timer_start
    logger.info("rewrite_node: '%s' → '%s' (%.2fs)", question, rewritten, elapsed)

    trace = dict(state.get("trace", {}))
    trace["rewrite"] = {
        "elapsed_ms": int(elapsed * 1000),
        "original": question,
        "rewritten": rewritten,
    }

    return {
        "rewritten_query": rewritten,
        "trace": trace,
    }


_ROUTE_SYSTEM = (
    "你是一个路由分类器。根据用户问题判断路由类型。\n"
    "规则：\n"
    "- 如果问题是简单的问候、闲聊、与简历无关的闲话，返回 direct_answer\n"
    "- 如果问题涉及简历内容、求职、技能、经历、教育、项目、工作等，返回 search\n"
    "- 不确定时返回 search\n"
    "只返回一个词：search 或 direct_answer"
)


async def _classify_route(query: str, model: str | None = None, user_id: int | None = None) -> str:
    result = await with_retry(
        llm_generate,
        _ROUTE_SYSTEM,
        f"问题：{query}",
        temperature=0.0,
        max_tokens=10,
        model=model,
        user_id=user_id,
        fallback="search",
    )
    result = (result or "search").strip().lower()
    if result not in ("search", "direct_answer"):
        logger.warning("route_node: LLM 返回非法值 '%s'，默认 search", result)
        return "search"
    return result


_GREETING_KEYWORDS = {
    "你好",
    "您好",
    "hi",
    "hello",
    "hey",
    "早上好",
    "下午好",
    "晚上好",
    "在吗",
    "在不在",
    "你是谁",
    "你是谁啊",
    "干嘛",
    "干什么",
    "谢谢",
    "感谢",
    "多谢",
    "拜拜",
    "再见",
    "bye",
}


def _is_trivial_greeting(query: str) -> bool:
    normalized = query.strip().lower().rstrip("!?！？。.")
    if len(normalized) <= 10 and normalized in _GREETING_KEYWORDS:
        return True
    return False


async def route_node(state: AgenticRAGState) -> dict:
    query = state.get("rewritten_query", state["question"])
    timer_start = time.monotonic()

    # 路由语义：direct_answer（问候，零 LLM 开销，经典 /ask 路径保留）
    # | fast（短/定向问题：单路快路径）| deep（复杂/跨文档：多路检索 + reflexion）。
    # 问候分支由 ReAct agent 侧 GenerateGreetingTool 兜底，但经典 /ask 仍需要。
    if _is_trivial_greeting(query):
        decision = "direct_answer"
    elif len(query.strip()) <= 20:
        decision = "fast"
    else:
        decision = "deep"

    elapsed = time.monotonic() - timer_start
    logger.info("route_node: '%s' → %s (%.2fs)", query, decision, elapsed)

    trace = dict(state.get("trace", {}))
    trace["route"] = {"elapsed_ms": int(elapsed * 1000), "decision": decision}

    return {
        "route_decision": decision,
        "trace": trace,
    }
