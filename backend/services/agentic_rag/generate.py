import json
import logging
import time
import re

from core.config import settings
from core.retry import with_retry
from services.agentic_rag.state import AgenticRAGState
from services.rag.pipeline import llm_generate
from services.rag.retrieval import reject_if_low_score

logger = logging.getLogger(__name__)

_EVAL_PASS_THRESHOLD = 0.4
_EVAL_MAX_RETRIES = 2


def _clamp_score(value: float) -> float:
    """将评分限制在 [0, 1] 范围内。"""
    return max(0.0, min(1.0, value))


def _compute_composite(completeness: float, accuracy: float, source_credibility: float) -> float:
    """计算综合评分：完整性 40% + 准确性 40% + 来源可信度 20%。"""
    return completeness * 0.4 + accuracy * 0.4 + source_credibility * 0.2


def _extract_sources(chunks: list[dict]) -> list[dict]:
    """抽取来源（T10 多源归因：携带 asset_id/asset_type/version 供溯源）。"""
    return [
        {
            "chunk_index": c.get("chunk_index", i),
            "text": c.get("text", ""),
            "section": c.get("section", "未知"),
            "rerank_score": c.get("rerank_score", 0.0),
            "asset_id": c.get("asset_id"),
            "asset_type": c.get("asset_type"),
            "version": c.get("version"),
        }
        for i, c in enumerate(chunks)
    ]


def _format_failed_tools(tool_errors: list[dict]) -> str:
    """把 tool_errors 渲染成可读的失败工具清单。"""
    lines = []
    for i, err in enumerate(tool_errors, 1):
        tool = err.get("tool", "unknown")
        error = err.get("error", "")
        extra = err.get("query")
        suffix = f"（查询：{extra}）" if extra else ""
        lines.append(f"{i}. {tool}{suffix}：{error}")
    return "\n".join(lines)


def _build_generate_prompt(chunks: list[dict], query: str, tool_errors: list[dict]) -> dict:
    """组装生成用 prompt（T10 多源归因）。

    来源带 [asset_id:v版本] 标注，要求答案对关键事实溯源；支持多份知识资产。
    阶段4 错误透传：tool_errors 非空时注入降级说明，告知 LLM 仅基于已有内容作答。
    """
    source_lines = []
    for i, c in enumerate(chunks):
        asset = c.get("asset_id")
        ver = c.get("version")
        label = f"[{asset}:v{ver}]" if asset is not None else f"[段落 {i + 1}]"
        source_lines.append(f"{label} {c.get('text', '')}")
    context = "\n\n".join(source_lines)

    system = (
        "你是一个求职知识助手。请基于给定的知识资产（可能来自多份简历/JD/面试记录）回答问题。"
        "每个来源都带 [asset_id:v版本] 标注。"
        "回答涉及具体事实时标注其来源资产；若资料中没有直接信息可进行合理推断，"
        "但需明确区分哪些是资料原文、哪些是推断。切忌编造事实。"
    )
    user = f"知识资产内容：\n{context}\n\n问题：{query}\n\n请给出简洁准确的回答。"
    prompt = {"system": system, "user": user}

    if tool_errors:
        failed_list = _format_failed_tools(tool_errors)
        prompt["system"] += (
            "\n\n【检索降级提示】本次回答所依赖的以下检索工具调用失败，相关来源可能缺失：\n"
            + failed_list
            + "\n请严格遵循：仅基于下方已提供的知识资产回答；"
            "若问题恰好涉及缺失的检索结果，请明确说明『部分检索工具失败，相关信息可能不完整』；"
            "绝对不要编造或猜测未出现的来源与事实。"
        )
        prompt["user"] += (
            "\n\n（提示：本次检索存在部分失败，已在上方的系统说明中列出，请据此作答并说明信息局限。）"
        )
    return prompt


async def generate_node(state: AgenticRAGState) -> dict:
    chunks = state.get("chunks", [])
    query = state.get("rewritten_query") or state["question"]
    # 阶段4 错误透传：读取上游 search/rerank 写入的 tool_errors。
    tool_errors = state.get("tool_errors", []) or []

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

    prompt = _build_generate_prompt(chunks, query, tool_errors)

    answer = await with_retry(
        llm_generate,
        prompt["system"],
        prompt["user"],
        temperature=settings.DEFAULT_GENERATE_TEMPERATURE,
        user_id=state.get("user_id"),
        fallback="服务暂时不可用，请稍后重试。",
    )

    elapsed = time.monotonic() - timer_start
    sources = _extract_sources(chunks)

    logger.info(
        "generate_node: query='%s' → %d chars, %d sources (%.2fs)",
        query[:50],
        len(answer),
        len(chunks),
        elapsed,
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
    "**来源可信度（source_credibility）**：引用的来源是否可靠、归因是否正确（T10）\n"
    "- 9-10: 来源直接相关、可信，且归因到正确的资产/版本\n"
    "- 7-8: 来源基本相关，归因基本正确\n"
    "- 5-6: 来源部分相关，或归因模糊（未指明具体资产）\n"
    "- 3-4: 来源不太相关，或归因错误\n"
    "- 1-2: 来源不相关，归因混乱\n"
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
        completeness = _clamp_score(float(data.get("completeness", 5)) / 10.0)
        accuracy = _clamp_score(float(data.get("accuracy", 5)) / 10.0)
        source_credibility = _clamp_score(float(data.get("source_credibility", 5)) / 10.0)
        feedback = str(data.get("feedback", ""))
        composite = _compute_composite(completeness, accuracy, source_credibility)
        return completeness, accuracy, source_credibility, composite, feedback
    except (json.JSONDecodeError, ValueError, TypeError):
        pass

    completeness_match = re.search(r'"completeness"\s*:\s*(\d+(?:\.\d+)?)', raw)
    accuracy_match = re.search(r'"accuracy"\s*:\s*(\d+(?:\.\d+)?)', raw)
    source_match = re.search(r'"source_credibility"\s*:\s*(\d+(?:\.\d+)?)', raw)

    if completeness_match and accuracy_match and source_match:
        completeness = _clamp_score(float(completeness_match.group(1)) / 10.0)
        accuracy = _clamp_score(float(accuracy_match.group(1)) / 10.0)
        source_credibility = _clamp_score(float(source_match.group(1)) / 10.0)
        composite = _compute_composite(completeness, accuracy, source_credibility)
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
        # P2-2 修复：拒答/零召回时不再直接短路，而是允许 Reflexion 重试
        # （should_retry=True）。零召回是最需要补充查询（supplement_queries）救场的
        # 场景，原实现把 should_retry 置 False，反思循环完全绕开——最该反思时不反思。
        # 轮数仍由 _route_after_evaluate 的 search_round <= 2 约束，不会无限循环；
        # 若反思也产不出补充方向，反思节点返回空 supplement_queries 即自然收敛。
        should_retry = search_round <= _EVAL_MAX_RETRIES
        trace["evaluate"] = {
            "elapsed_ms": int(elapsed * 1000),
            "skipped": True,
            "reason": "no_answer_or_rejection",
            "should_retry": should_retry,
        }
        return {
            "eval_score": 0.0,
            "eval_feedback": "无有效答案，需要补充检索",
            "should_retry": should_retry,
            "completeness_score": 0.0,
            "accuracy_score": 0.0,
            "source_credibility_score": 0.0,
            "eval_forced": False,
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
            "eval_forced": True,
            "trace": trace,
        }

    eval_user = _build_eval_user(question, answer, sources)
    raw = await with_retry(
        llm_generate,
        _EVAL_SYSTEM,
        eval_user,
        temperature=0.0,
        max_tokens=400,
        model=settings.JUDGE_MODEL if settings.JUDGE_ENABLED else None,
        user_id=state.get("user_id"),
        fallback='{"completeness": 5, "accuracy": 5, "source_credibility": 5, "feedback": "评估服务暂时不可用"}',
    )

    completeness, accuracy, source_credibility, composite, feedback = _parse_eval_response(raw)
    should_retry = composite < _EVAL_PASS_THRESHOLD

    elapsed = time.monotonic() - timer_start
    logger.info(
        "evaluate_node: completeness=%.2f accuracy=%.2f source=%.2f composite=%.2f retry=%s (%.2fs)",
        completeness,
        accuracy,
        source_credibility,
        composite,
        should_retry,
        elapsed,
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
        "eval_forced": False,
        "trace": trace,
    }
