import json
import logging
import time
import re

from core.retry import with_retry
from services.agentic_rag.state import AgenticRAGState
from services.rag_service import llm_generate, build_prompt, reject_if_low_score

logger = logging.getLogger(__name__)

_GENERATE_TEMPERATURE = 0.3
_EVAL_PASS_THRESHOLD = 0.6
_EVAL_MAX_RETRIES = 2


def _extract_sources(chunks: list[dict]) -> list[dict]:
    return [
        {
            "chunk_index": c.get("chunk_index", i),
            "text": c.get("text", ""),
            "section": c.get("section", "未知"),
            "rerank_score": c.get("rerank_score", 0.0),
        }
        for i, c in enumerate(chunks)
    ]


async def generate_node(state: AgenticRAGState) -> dict:
    chunks = state.get("chunks", [])
    query = state.get("rewritten_query") or state["question"]

    timer_start = time.monotonic()

    if not chunks or reject_if_low_score(chunks):
        elapsed = time.monotonic() - timer_start
        logger.info("generate_node: no valid chunks, returning rejection")
        trace = dict(state.get("trace", {}))
        trace["generate"] = {
            "elapsed_ms": int(elapsed * 1000),
            "chunk_count": 0,
            "rejected": True,
        }
        return {
            "answer": "抱歉，简历中未提及该信息。",
            "sources": [],
            "trace": trace,
        }

    prompt = build_prompt([c["text"] for c in chunks], query)

    answer = await with_retry(
        llm_generate,
        prompt["system"],
        prompt["user"],
        temperature=_GENERATE_TEMPERATURE,
        fallback="服务暂时不可用，请稍后重试。",
    )

    elapsed = time.monotonic() - timer_start
    sources = _extract_sources(chunks)

    logger.info(
        "generate_node: query='%s' → %d chars, %d sources (%.2fs)",
        query[:50], len(answer), len(chunks), elapsed,
    )

    trace = dict(state.get("trace", {}))
    trace["generate"] = {
        "elapsed_ms": int(elapsed * 1000),
        "chunk_count": len(chunks),
        "answer_length": len(answer),
        "rejected": False,
    }

    return {
        "answer": answer,
        "sources": sources,
        "trace": trace,
    }


_EVAL_SYSTEM = (
    "你是一个简历问答质量评估专家。请从三个维度评估以下回答的质量。\n\n"
    "评分标准（每个维度 0-10 整数）：\n\n"
    "**完整性（completeness）**：答案是否覆盖了问题的所有方面\n"
    "- 9-10: 完全覆盖问题的所有方面\n"
    "- 7-8: 覆盖了大部分方面，有少量遗漏\n"
    "- 5-6: 覆盖了部分方面，有明显遗漏\n"
    "- 3-4: 覆盖很少方面，遗漏严重\n"
    "- 1-2: 几乎没有覆盖\n"
    "- 0: 完全不相关\n\n"
    "**准确性（accuracy）**：答案是否与简历内容一致\n"
    "- 9-10: 完全准确，与简历内容一致\n"
    "- 7-8: 基本准确，有少量不精确\n"
    "- 5-6: 部分准确，有错误信息\n"
    "- 3-4: 大量错误\n"
    "- 1-2: 严重不准确\n"
    "- 0: 完全错误\n\n"
    "**来源可信度（source_credibility）**：引用的来源是否可靠\n"
    "- 9-10: 来源直接相关且可信\n"
    "- 7-8: 来源基本相关\n"
    "- 5-6: 来源部分相关\n"
    "- 3-4: 来源不太相关\n"
    "- 1-2: 来源不相关\n"
    "- 0: 没有引用来源\n\n"
    "请严格按以下 JSON 格式返回（不要包含其他文字）：\n"
    '{"completeness": <0-10>, "accuracy": <0-10>, "source_credibility": <0-10>, "feedback": "<具体评价>"}'
)


def _build_eval_user(question: str, answer: str, sources: list[dict]) -> str:
    source_text = "\n\n".join(
        f"[来源 {i + 1}] {s.get('section', '未知')}: {s.get('text', '')[:200]}"
        for i, s in enumerate(sources[:5])
    )
    return (
        f"用户问题：{question}\n\n"
        f"回答内容：{answer}\n\n"
        f"参考来源：\n{source_text}\n\n"
        "请评估回答质量。"
    )


def _parse_eval_response(raw: str) -> tuple[float, float, float, float, str]:
    default = (0.5, 0.5, 0.5, 0.5, "评估解析失败")

    if not raw:
        return 0.5, 0.5, 0.5, 0.5, "评估返回为空"

    try:
        data = json.loads(raw.strip())
        completeness = float(data.get("completeness", 5)) / 10.0
        accuracy = float(data.get("accuracy", 5)) / 10.0
        source_credibility = float(data.get("source_credibility", 5)) / 10.0
        feedback = str(data.get("feedback", ""))

        completeness = max(0.0, min(1.0, completeness))
        accuracy = max(0.0, min(1.0, accuracy))
        source_credibility = max(0.0, min(1.0, source_credibility))

        composite = completeness * 0.4 + accuracy * 0.4 + source_credibility * 0.2

        return completeness, accuracy, source_credibility, composite, feedback
    except (json.JSONDecodeError, ValueError, TypeError):
        pass

    completeness_match = re.search(r'"completeness"\s*:\s*(\d+(?:\.\d+)?)', raw)
    accuracy_match = re.search(r'"accuracy"\s*:\s*(\d+(?:\.\d+)?)', raw)
    source_match = re.search(r'"source_credibility"\s*:\s*(\d+(?:\.\d+)?)', raw)

    if completeness_match and accuracy_match and source_match:
        completeness = float(completeness_match.group(1)) / 10.0
        accuracy = float(accuracy_match.group(1)) / 10.0
        source_credibility = float(source_match.group(1)) / 10.0

        completeness = max(0.0, min(1.0, completeness))
        accuracy = max(0.0, min(1.0, accuracy))
        source_credibility = max(0.0, min(1.0, source_credibility))

        composite = completeness * 0.4 + accuracy * 0.4 + source_credibility * 0.2

        feedback_match = re.search(r'"feedback"\s*:\s*"([^"]*)"', raw)
        feedback = feedback_match.group(1) if feedback_match else ""

        return completeness, accuracy, source_credibility, composite, feedback

    logger.warning("evaluate_node: failed to parse eval response: %s", raw[:100])
    return default


async def evaluate_node(state: AgenticRAGState) -> dict:
    question = state.get("rewritten_query") or state["question"]
    answer = state.get("answer", "")
    sources = state.get("sources", [])
    search_round = state.get("search_round", 0)

    timer_start = time.monotonic()

    trace_data = state.get("trace", {})
    is_rejected = trace_data.get("generate", {}).get("rejected", False)
    if not answer or is_rejected:
        elapsed = time.monotonic() - timer_start
        trace = dict(state.get("trace", {}))
        trace["evaluate"] = {
            "elapsed_ms": int(elapsed * 1000),
            "skipped": True,
            "reason": "no_answer_or_rejection",
        }
        return {
            "eval_score": 0.0,
            "eval_feedback": "无有效答案",
            "should_retry": False,
            "completeness_score": 0.0,
            "accuracy_score": 0.0,
            "source_credibility_score": 0.0,
            "trace": trace,
        }

    if search_round > _EVAL_MAX_RETRIES:
        elapsed = time.monotonic() - timer_start
        logger.info("evaluate_node: max retries reached (round=%d), forcing pass", search_round)
        trace = dict(state.get("trace", {}))
        trace["evaluate"] = {
            "elapsed_ms": int(elapsed * 1000),
            "skipped": True,
            "reason": "max_retries_reached",
        }
        return {
            "eval_score": 0.5,
            "eval_feedback": "已达最大重试次数",
            "should_retry": False,
            "completeness_score": 0.5,
            "accuracy_score": 0.5,
            "source_credibility_score": 0.5,
            "trace": trace,
        }

    eval_user = _build_eval_user(question, answer, sources)
    raw = await with_retry(
        llm_generate,
        _EVAL_SYSTEM,
        eval_user,
        temperature=0.0,
        max_tokens=400,
        fallback='{"completeness": 5, "accuracy": 5, "source_credibility": 5, "feedback": "评估服务暂时不可用"}',
    )

    completeness, accuracy, source_credibility, composite, feedback = _parse_eval_response(raw)
    should_retry = composite < _EVAL_PASS_THRESHOLD

    elapsed = time.monotonic() - timer_start
    logger.info(
        "evaluate_node: completeness=%.2f accuracy=%.2f source=%.2f composite=%.2f retry=%s (%.2fs)",
        completeness, accuracy, source_credibility, composite, should_retry, elapsed,
    )

    trace = dict(state.get("trace", {}))
    trace["evaluate"] = {
        "elapsed_ms": int(elapsed * 1000),
        "completeness": completeness,
        "accuracy": accuracy,
        "source_credibility": source_credibility,
        "composite": composite,
        "should_retry": should_retry,
        "skipped": False,
    }

    return {
        "eval_score": composite,
        "eval_feedback": feedback,
        "should_retry": should_retry,
        "completeness_score": completeness,
        "accuracy_score": accuracy,
        "source_credibility_score": source_credibility,
        "trace": trace,
    }
