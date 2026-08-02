import json
import logging
import time
import re

from core.config import settings
from core.retry import with_retry
from services.agentic_rag.state import AgenticRAGState
from services.rag.pipeline import llm_generate

logger = logging.getLogger(__name__)

_MAX_SUPPLEMENT_QUERIES = 3
_MAX_REFLECTION_ROUNDS = 2


_REFLECTION_SYSTEM = (
    "你是一个求职知识问答质量分析专家。你的任务是分析为什么答案质量不佳，并给出改进建议。\n\n"
    "你需要做四件事：\n"
    "1. **分析问题**：为什么这个答案不好？（不完整？不准确？来源不可靠？归因错误？）\n"
    "2. **识别缺失**：哪些关键信息没有找到？\n"
    "3. **生成查询**：应该搜索什么来补充这些信息？\n"
    "4. **scope_expansion**：如果答案是因为『当前检索范围缺某类资产』（如回答 JD 相关问题但检索范围没有 jd 资产；"
    "或需要对比多个版本但只有一份），列出应补充的资产类型（resume/jd/interview/note）。不需要则给空数组。\n\n"
    "请严格按以下 JSON 格式返回（不要包含其他文字）：\n"
    "{\n"
    '  "reflection": "<分析答案为什么不好的具体原因>",\n'
    '  "missing_info": ["<缺失信息1>", "<缺失信息2>", ...],\n'
    '  "supplement_queries": ["<补充查询1>", "<补充查询2>", ...],\n'
    '  "scope_expansion": ["<缺失资产类型1>", ...]\n'
    "}\n\n"
    "注意：\n"
    "- supplement_queries 应该是具体的搜索查询，而不是笼统的描述\n"
    "- 每个查询应该针对一个具体的缺失信息\n"
    "- 最多生成 3 个查询\n"
    "- scope_expansion 只填资产类型（resume/jd/interview/note），最多 2 个，不需要填空数组"
)


def _build_reflection_user(
    question: str,
    answer: str,
    sources: list[dict],
    eval_feedback: str,
    completeness_score: float,
    accuracy_score: float,
    source_credibility_score: float,
    previous_reflections: list[str],
    scope: dict[str, list[int]] | None = None,
) -> str:
    source_text = "\n\n".join(
        f"[来源 {i + 1}] {s.get('section', '未知')}: {s.get('text', '')[:150]}"
        for i, s in enumerate(sources[:5])
    )

    prev_reflections_text = ""
    if previous_reflections:
        prev_reflections_text = "\n\n**之前的反思（避免重复）**：\n" + "\n".join(
            f"- {r}" for r in previous_reflections[-2:]
        )

    # T10：告知当前检索范围，供 scope_expansion 判断缺哪类资产
    scope_text = str(scope) if scope else "未知"

    return (
        f"**用户问题**：{question}\n\n"
        f"**当前检索范围（scope）**：{scope_text}\n\n"
        f"**当前答案**：{answer}\n\n"
        f"**参考来源**：\n{source_text}\n\n"
        f"**评估结果**：\n"
        f"- 综合评分：{completeness_score:.1%}（完整性） + {accuracy_score:.1%}（准确性） + {source_credibility_score:.1%}（来源可信度）\n"
        f"- 评估反馈：{eval_feedback}\n"
        f"{prev_reflections_text}\n\n"
        "请分析答案问题并给出改进建议（含是否需要扩充检索范围的资产类型）。"
    )


def _parse_reflection_response(raw: str) -> tuple[str, list[str], list[str], list[str]]:
    default_reflection = "解析失败，无法分析"
    default_missing = ["无法识别缺失信息"]
    default_queries = []
    default_scope_expansion = []

    if not raw:
        return default_reflection, default_missing, default_queries, default_scope_expansion

    try:
        data = json.loads(raw.strip())
        reflection = str(data.get("reflection", default_reflection))
        missing_info = list(data.get("missing_info", default_missing))
        supplement_queries = list(data.get("supplement_queries", default_queries))[
            :_MAX_SUPPLEMENT_QUERIES
        ]
        scope_expansion = list(data.get("scope_expansion", default_scope_expansion))[:2]
        return reflection, missing_info, supplement_queries, scope_expansion
    except (json.JSONDecodeError, ValueError, TypeError):
        pass

    reflection_match = re.search(r'"reflection"\s*:\s*"([^"]*)"', raw)
    reflection = reflection_match.group(1) if reflection_match else default_reflection

    missing_match = re.search(r'"missing_info"\s*:\s*\[([^\]]*)\]', raw)
    if missing_match:
        missing_text = missing_match.group(1)
        missing_info = re.findall(r'"([^"]*)"', missing_text)
    else:
        missing_info = default_missing

    queries_match = re.search(r'"supplement_queries"\s*:\s*\[([^\]]*)\]', raw)
    if queries_match:
        queries_text = queries_match.group(1)
        supplement_queries = re.findall(r'"([^"]*)"', queries_text)[:_MAX_SUPPLEMENT_QUERIES]
    else:
        supplement_queries = default_queries

    scope_match = re.search(r'"scope_expansion"\s*:\s*\[([^\]]*)\]', raw)
    if scope_match:
        scope_text = scope_match.group(1)
        scope_expansion = re.findall(r'"([^"]*)"', scope_text)[:2]
    else:
        scope_expansion = default_scope_expansion

    logger.warning("reflection_node: degraded parse, raw=%s", raw[:100])
    return reflection, missing_info, supplement_queries, scope_expansion


async def self_reflection_node(state: AgenticRAGState) -> dict:
    question = state.get("rewritten_query") or state["question"]
    answer = state.get("answer", "")
    sources = state.get("sources", [])
    eval_feedback = state.get("eval_feedback", "")
    completeness_score = state.get("completeness_score", 0.0)
    accuracy_score = state.get("accuracy_score", 0.0)
    source_credibility_score = state.get("source_credibility_score", 0.0)
    reflection_round = state.get("reflection_round", 0)

    timer_start = time.monotonic()

    previous_reflections = []
    trace = state.get("trace", {})
    for i in range(1, reflection_round + 1):
        prev_trace = trace.get(f"self_reflection_{i}", {})
        if prev_trace.get("reflection"):
            previous_reflections.append(prev_trace["reflection"])

    scope = state.get("scope")
    reflection_user = _build_reflection_user(
        question=question,
        answer=answer,
        sources=sources,
        eval_feedback=eval_feedback,
        completeness_score=completeness_score,
        accuracy_score=accuracy_score,
        source_credibility_score=source_credibility_score,
        previous_reflections=previous_reflections,
        scope=scope,
    )

    raw = await with_retry(
        llm_generate,
        _REFLECTION_SYSTEM,
        reflection_user,
        temperature=0.2,
        max_tokens=500,
        model=settings.JUDGE_MODEL if settings.JUDGE_ENABLED else None,
        fallback=(
            '{"reflection": "反思服务暂时不可用", "missing_info": [], '
            '"supplement_queries": [], "scope_expansion": []}'
        ),
    )

    reflection, missing_info, supplement_queries, scope_expansion = _parse_reflection_response(
        raw
    )

    elapsed = time.monotonic() - timer_start
    new_round = reflection_round + 1

    logger.info(
        "self_reflection_node: round=%d, missing=%d, queries=%d, scope_expansion=%s (%.2fs)",
        new_round,
        len(missing_info),
        len(supplement_queries),
        scope_expansion,
        elapsed,
    )

    trace = dict(state.get("trace", {}))
    trace[f"self_reflection_{new_round}"] = {
        "elapsed_ms": int(elapsed * 1000),
        "reflection": reflection[:200],
        "missing_count": len(missing_info),
        "query_count": len(supplement_queries),
        "scope_expansion": scope_expansion,
    }

    return {
        "reflection_result": reflection,
        "missing_info": missing_info,
        "supplement_queries": supplement_queries,
        "scope_expansion": scope_expansion,
        "reflection_round": new_round,
        "trace": trace,
    }
