"""评估 harness：脚本化假模型驱动 react_loop + 黄金判定 + 状态哈希 + pass^k。

机制参考：
- tau-bench ``Env.calculate_reward``：reward ∈ {0,1}，判据 = 最终状态等价 + outputs 回传完整
- pydantic-ai ``TestModel``：脚本化假模型按轮返回工具调用，断言实际调用序列

判定（全有或全无，reward ∈ {0,1}）：
1. 成功轨迹匹配：process_trace 中成功执行的工具序列 == gold_actions（名称 + 关键参数）
   —— 坏调用（tool_error）不计入，验证"错误回灌后修正"的契约化闭环
2. outputs 子串匹配：required_outputs 全部出现在最终回答（tau-bench ``output.lower() in content.lower()``）
3. 状态哈希：规范化状态指纹（成功轨迹 + 最终回答 + token）——审计与回归比对信号

pass^k：``C(c, k) / C(n, k)``（n 次 trial 中 c 次成功，任抽 k 次全过的概率，超几何组合估计）。
"""

import hashlib
import json
import logging
import math
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from unittest.mock import AsyncMock, MagicMock, patch

from services.react_agent.loop import react_loop
from services.rag.pipeline import ToolCall

from tests.agent_eval.golden_tasks import EvalTask, ScriptRound, ToolCallSpec

logger = logging.getLogger(__name__)

# 每工具必填参数（契约化校验的简化模拟：缺参 → ToolRetryError 回灌）
_REQUIRED_ARGS: dict[str, set[str]] = {
    "diagnose_resume": {"resume_id"},
    "save_memory": {"snippet"},
    "recall_memory": {"query"},
    "jd_match": {"resume_id"},
    "get_resume_content": {"resume_id"},
    "search_resume": {"resume_id", "query"},
    "answer_from_index": {"question"},
}


@dataclass
class EvalResult:
    """单次评估结果（reward ∈ {0,1}，tau-bench 风格）。"""

    task_name: str
    passed: bool
    actual_actions: list[ToolCallSpec] = field(default_factory=list)
    answer: str = ""
    state_hash: str = ""
    failure: str | None = None  # 未通过时的判据说明


# ═══════════════════════════════════════════════════════════════
# 状态哈希（tau-bench state hash：规范化投影 → sha256）
# ═══════════════════════════════════════════════════════════════


def _normalize_answer(text: str) -> str:
    return " ".join((text or "").strip().split())


def compute_state_hash(answer: str, success_actions: list[ToolCallSpec], usage: dict) -> str:
    """规范化状态指纹：成功轨迹 + 最终回答 + token 消耗 → sha256。

    判定/审计用：同一任务重复运行的哈希应稳定（确定性验证）。
    """
    projection = {
        "answer": _normalize_answer(answer),
        "calls": [(a.name, sorted(a.args.items())) for a in success_actions],
        "usage": {
            k: int(v)
            for k, v in (usage or {}).items()
            if k in ("prompt_tokens", "completion_tokens")
        },
    }
    canonical = json.dumps(projection, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ═══════════════════════════════════════════════════════════════
# pass^k（tau-bench run.py 超几何公式）
# ═══════════════════════════════════════════════════════════════


def pass_at_k(successes: int, trials: int, k: int) -> float:
    """n 次 trial 中 c 次成功，任抽 k 次全部成功的概率：C(c,k)/C(n,k)。

    - k=1：经验通过率 c/n
    - k=n：仅当全部成功时为 1（最严格）
    参数非法（k>n 或 c<k）返回 0.0。
    """
    if trials <= 0 or k <= 0 or k > trials or successes < k:
        return 0.0
    return math.comb(successes, k) / math.comb(trials, k)


# ═══════════════════════════════════════════════════════════════
# 假模型：按脚本生成流式响应
# ═══════════════════════════════════════════════════════════════


def _make_stream_response(round_: ScriptRound, usage: dict | None = None):
    """构造 llm_generate_with_tools_stream 的 async generator（pipeline 流式事件协议）。

    round_.tool_calls 为空 → 无工具直接回答（content 即最终答案）。
    """

    async def _gen():
        if round_.content:
            yield {"type": "token", "content": round_.content}
        if usage:
            yield {
                "type": "usage",
                "prompt_tokens": usage.get("prompt_tokens", 0),
                "completion_tokens": usage.get("completion_tokens", 0),
            }
        tool_calls = [
            ToolCall(id=f"tc_{i}", name=tc.name, arguments=json.dumps(tc.args, ensure_ascii=False))
            for i, tc in enumerate(round_.tool_calls)
        ]
        yield {"type": "done", "content": round_.content, "tool_calls": tool_calls}

    return _gen()


def _make_tool_class():
    """契约化模拟工具注册表（模拟真实 get_tool_by_name 行为）。

    - _REQUIRED_ARGS 中注册的工具名 → 返回 mock 工具类；execute 模拟契约校验：缺参
      → ToolRetryError（对齐工具基类 format_validation_error 语义），合法 → 固定成功文本
    - 未注册工具名（含脚本故意注入的 nonexistent_tool）→ 返回 None，
      对齐真实 TOOL_REGISTRY：loop 走「工具不存在」错误分支回灌
    """
    from services.react_agent.tools.base import ToolRetryError

    def _build_execute(name: str):
        async def _execute(**_kwargs):
            required = _REQUIRED_ARGS.get(name, set())
            missing = required - set(_kwargs)
            if missing:
                raise ToolRetryError(f"缺少必填参数: {sorted(missing)}")
            return f"{name} 执行成功"

        return _execute

    def _factory(name: str):
        if name not in _REQUIRED_ARGS:
            return None  # 未知工具：与真实 TOOL_REGISTRY 行为一致
        cls = MagicMock()
        cls.return_value.execute = AsyncMock(side_effect=_build_execute(name))
        cls.return_value.last_usage = {"prompt_tokens": 0, "completion_tokens": 0}
        cls.return_value.sources = []
        return cls

    mock_tool_class = MagicMock()
    mock_tool_class.side_effect = _factory  # get_tool_by_name(name) → 按名工厂
    return mock_tool_class


# ═══════════════════════════════════════════════════════════════
# 运行单个任务
# ═══════════════════════════════════════════════════════════════


def _extract_success_actions(process_trace: list[dict]) -> list[ToolCallSpec]:
    """从 process_trace 提取成功执行的工具序列（tool_call 且未对应 tool_error）。

    tool_error 事件带 name（loop.py:330-335），坏调用不计入成功序列——
    这使"坏调用回灌后修正"的任务只统计修正后的合法调用（契约化闭环的判定语义）。
    """
    error_names: list[str] = [e["name"] for e in process_trace if e.get("type") == "tool_error"]
    out: list[ToolCallSpec] = []
    for e in process_trace:
        if e.get("type") != "tool_call":
            continue
        name = e["name"]
        if name in error_names:
            error_names.remove(name)  # 只抵消同一次调用
            continue
        args = e.get("arguments") or "{}"
        try:
            parsed = json.loads(args) if isinstance(args, str) else args
        except (json.JSONDecodeError, TypeError):
            parsed = {}
        out.append(ToolCallSpec(name=name, args=parsed))
    return out


def _actions_match(actual: list[ToolCallSpec], gold: tuple[ToolCallSpec, ...]) -> bool:
    """轨迹匹配：名称精确 + 参数关键字段包含（宽松：gold 指定字段值在 actual 中命中即可）。"""
    if len(actual) != len(gold):
        return False
    for a, g in zip(actual, gold):
        if a.name != g.name:
            return False
        for key, value in g.args.items():
            if a.args.get(key) != value:
                return False
    return True


async def run_task(
    task: EvalTask,
    *,
    db=None,
    event_callback: Callable[[dict], Awaitable[None]] | None = None,
) -> EvalResult:
    """运行一个黄金任务：脚本化假模型驱动 react_loop → 三元判定。

    假模型按 task.script 每轮注入工具调用；工具层按 _REQUIRED_ARGS 模拟契约校验
    （缺参 → ToolRetryError 回灌），其余依赖（配额/L1/system prompt）全部 mock。
    """
    stream_mock = MagicMock(side_effect=[_make_stream_response(r) for r in task.script])
    tool_class = _make_tool_class()

    with (
        patch("services.react_agent.loop.llm_generate_with_tools", new_callable=AsyncMock),
        patch(
            "services.react_agent.loop.assemble_system_prompt", new_callable=AsyncMock
        ) as mock_sys,
        patch("services.react_agent.loop.check_quota", new_callable=AsyncMock) as mock_quota,
        patch("services.react_agent.loop.llm_generate_with_tools_stream", stream_mock),
        patch("services.react_agent.loop.get_tool_by_name", tool_class),
        patch("services.react_agent.loop.get_agent_schemas", return_value=[]),
        patch("services.react_agent.loop.manage_l1_context") as mock_l1,
    ):
        mock_sys.return_value = "eval system prompt"
        mock_quota.return_value = (True, None)
        mock_l1.side_effect = lambda msgs, **kw: msgs

        result = await react_loop(
            db=db or AsyncMock(),
            user_id=1,
            resume_id=1,
            question=task.instruction,
            event_callback=event_callback,
        )

    actual = _extract_success_actions(result.process_trace)
    hash_value = compute_state_hash(result.answer, actual, result.usage)

    # ── 三元判定（tau-bench reward ∈ {0,1}）──
    failures: list[str] = []
    if not _actions_match(actual, task.gold_actions):
        failures.append(
            f"轨迹不匹配: 实际={[(a.name, a.args) for a in actual]} 期望={[(g.name, g.args) for g in task.gold_actions]}"
        )
    answer_lower = (result.answer or "").lower()
    for out in task.required_outputs:
        if out.lower() not in answer_lower:
            failures.append(f"输出缺失: {out!r} 不在最终回答中")

    return EvalResult(
        task_name=task.name,
        passed=not failures,
        actual_actions=actual,
        answer=result.answer,
        state_hash=hash_value,
        failure="; ".join(failures) or None,
    )


# ═══════════════════════════════════════════════════════════════
# 批量评估 + pass^k 报告
# ═══════════════════════════════════════════════════════════════


async def run_evals(tasks, trials: int = 1) -> dict[str, list[EvalResult]]:
    """跑评估套件：每任务 trials 次（确定性，同任务重复运行结果一致）。"""
    reports: dict[str, list[EvalResult]] = {}
    for task in tasks:
        reports[task.name] = [await run_task(task) for _ in range(trials)]
    return reports


def summarize(reports: dict[str, list[EvalResult]]) -> dict:
    """汇总评估报告：每任务通过数 + pass@k（任务池统计）。

    pass@k 语义（tau-bench）：任抽 k 个 trial 全部通过的概率。单任务确定性时
    等价于 C(c,k)/C(n,k)；跨任务池统计反映套件整体稳定性。
    """
    summary: dict = {"tasks": {}, "pass_at_k": {}}
    per_task = {name: [r.passed for r in results] for name, results in reports.items()}
    total_trials = sum(len(v) for v in per_task.values())
    total_passed = sum(sum(1 for p in v if p) for v in per_task.values())
    for name, passed_list in per_task.items():
        n = len(passed_list)
        c = sum(1 for p in passed_list if p)
        summary["tasks"][name] = {
            "passed": c,
            "trials": n,
            "pass_rate": round(c / n, 3) if n else 0.0,
        }
    if total_trials:
        for k in range(1, min(total_trials, 3) + 1):
            summary["pass_at_k"][k] = round(pass_at_k(total_passed, total_trials, k), 4)
    return summary
