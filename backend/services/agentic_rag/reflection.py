import json
import logging
import time
import re
from enum import Enum

from core.config import settings
from core.retry import with_retry
from services.agentic_rag.state import AgenticRAGState
from services.rag.pipeline import llm_generate

logger = logging.getLogger(__name__)

_MAX_SUPPLEMENT_QUERIES = 3
_MAX_REFLECTION_ROUNDS = 2


class FaultType(str, Enum):
    """D2: 失败类型分类，供定向恢复选择策略。

    - ``used_wrong_tool``: 用错了工具（应换一个更合适的工具）
    - ``used_wrong_tool_argument``: 工具用对了但参数不正确
    - ``goal_partially_completed``: 目标部分完成（覆盖不全/遗漏，默认值）
    - ``user_info_missing``: 缺少完成任务所需的用户信息（需向用户澄清）
    """

    USED_WRONG_TOOL = "used_wrong_tool"
    USED_WRONG_TOOL_ARGUMENT = "used_wrong_tool_argument"
    GOAL_PARTIALLY_COMPLETED = "goal_partially_completed"
    USER_INFO_MISSING = "user_info_missing"


# 合法 fault_type 值集合 + 默认值（评估不足且模型未给出分类时兜底）
_VALID_FAULT_TYPES: set[str] = {ft.value for ft in FaultType}
_DEFAULT_FAULT_TYPE = FaultType.GOAL_PARTIALLY_COMPLETED.value

# D2 失败类型侧信道：key=(user_id, question) → 最近一次反思判定的 fault_type。
# react_agent.loop 在 stuck 时读取（_classify_recent_fault 优先取此），实现跨模块定向恢复。
_FAULT_TYPE_REGISTRY_MAX = 200
_fault_type_registry: dict[tuple[int, str], str] = {}


def record_fault_type(user_id: int, question: str, fault_type: str) -> None:
    """D2: 记录最近一次反思判定的 fault_type（供 loop 侧信道读取）。"""
    if not fault_type:
        return
    _fault_type_registry[(user_id, question)] = fault_type
    # 防无限增长：超过上限时逐出最旧条目
    if len(_fault_type_registry) > _FAULT_TYPE_REGISTRY_MAX:
        for key in list(_fault_type_registry)[: len(_fault_type_registry) - _FAULT_TYPE_REGISTRY_MAX]:
            _fault_type_registry.pop(key, None)


def get_fault_type(user_id: int, question: str) -> str | None:
    """D2: 读取最近一次反思判定的 fault_type。"""
    return _fault_type_registry.get((user_id, question))


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
    '  "fault_type": "<失败类型，见下方枚举>",\n'
    '  "fault_assignment": "<失败归因：描述问题出在哪个环节/谁身上>",\n'
    '  "missing_info": ["<缺失信息1>", "<缺失信息2>", ...],\n'
    '  "supplement_queries": ["<补充查询1>", "<补充查询2>", ...],\n'
    '  "scope_expansion": ["<缺失资产类型1>", ...]\n'
    "}\n\n"
    "fault_type 枚举：\n"
    '- "used_wrong_tool"：用错了工具，应换一个更合适的工具\n'
    '- "used_wrong_tool_argument"：工具用对了但参数不正确\n'
    '- "goal_partially_completed"：目标部分完成（覆盖不全/遗漏，无法确定时用此默认值）\n'
    '- "user_info_missing"：缺少完成任务所需的用户信息，需向用户澄清\n\n'
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

    # 告知当前检索范围，供 scope_expansion 判断缺哪类资产
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


def _normalize_fault_type(raw_value) -> str:
    """把模型返回的 fault_type 归一化到合法枚举；非法/缺失回退默认 goal_partially_completed。"""
    if isinstance(raw_value, str) and raw_value in _VALID_FAULT_TYPES:
        return raw_value
    return _DEFAULT_FAULT_TYPE


def _parse_reflection_response(
    raw: str,
) -> tuple[str, str, str, list[str], list[str], list[str]]:
    """解析反思响应。

    Returns:
        (reflection, fault_type, fault_assignment, missing_info, supplement_queries, scope_expansion)
    """
    default_reflection = "解析失败，无法分析"
    default_fault_type = _DEFAULT_FAULT_TYPE
    default_fault_assignment = "无法识别失败归因"
    default_missing = ["无法识别缺失信息"]
    default_queries = []
    default_scope_expansion = []

    if not raw:
        return (
            default_reflection,
            default_fault_type,
            default_fault_assignment,
            default_missing,
            default_queries,
            default_scope_expansion,
        )

    try:
        data = json.loads(raw.strip())
        reflection = str(data.get("reflection", default_reflection))
        fault_type = _normalize_fault_type(data.get("fault_type"))
        fault_assignment = str(data.get("fault_assignment", default_fault_assignment))
        missing_info = list(data.get("missing_info", default_missing))
        supplement_queries = list(data.get("supplement_queries", default_queries))[
            :_MAX_SUPPLEMENT_QUERIES
        ]
        scope_expansion = list(data.get("scope_expansion", default_scope_expansion))[:2]
        return (
            reflection,
            fault_type,
            fault_assignment,
            missing_info,
            supplement_queries,
            scope_expansion,
        )
    except (json.JSONDecodeError, ValueError, TypeError):
        pass

    reflection_match = re.search(r'"reflection"\s*:\s*"([^"]*)"', raw)
    reflection = reflection_match.group(1) if reflection_match else default_reflection

    fault_match = re.search(r'"fault_type"\s*:\s*"([^"]*)"', raw)
    fault_type = (
        _normalize_fault_type(fault_match.group(1)) if fault_match else default_fault_type
    )

    assignment_match = re.search(r'"fault_assignment"\s*:\s*"([^"]*)"', raw)
    fault_assignment = (
        assignment_match.group(1) if assignment_match else default_fault_assignment
    )

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
    return (
        reflection,
        fault_type,
        fault_assignment,
        missing_info,
        supplement_queries,
        scope_expansion,
    )


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
        user_id=state.get("user_id"),
        fallback=(
            '{"reflection": "反思服务暂时不可用", "missing_info": [], '
            '"supplement_queries": [], "scope_expansion": []}'
        ),
    )

    (
        reflection,
        fault_type,
        fault_assignment,
        missing_info,
        supplement_queries,
        scope_expansion,
    ) = _parse_reflection_response(raw)

    # D2 失败分类侧信道：以原始问题为 key 记录最近一次 fault_type，
    # 供 react_agent.loop 的 stuck 定向恢复读取（best-effort，不影响反思本身）。
    try:
        record_fault_type(state.get("user_id"), state.get("question", ""), fault_type)
    except Exception:
        logger.debug("record_fault_type 失败（忽略）", exc_info=True)

    elapsed = time.monotonic() - timer_start
    new_round = reflection_round + 1

    logger.info(
        "self_reflection_node: round=%d, fault_type=%s, missing=%d, queries=%d, scope_expansion=%s (%.2fs)",
        new_round,
        fault_type,
        len(missing_info),
        len(supplement_queries),
        scope_expansion,
        elapsed,
    )

    trace = dict(state.get("trace", {}))
    trace[f"self_reflection_{new_round}"] = {
        "elapsed_ms": int(elapsed * 1000),
        "reflection": reflection[:200],
        "fault_type": fault_type,
        "fault_assignment": fault_assignment[:200],
        "missing_count": len(missing_info),
        "query_count": len(supplement_queries),
        "scope_expansion": scope_expansion,
    }

    return {
        "reflection_result": reflection,
        "fault_type": fault_type,
        "fault_assignment": fault_assignment,
        "missing_info": missing_info,
        "supplement_queries": supplement_queries,
        "scope_expansion": scope_expansion,
        "reflection_round": new_round,
        "trace": trace,
    }
