"""T16: ReAct 核心循环。

手写 asyncio ReAct 循环（非 LangGraph）：
- 配额预检 → 不足则直接返回
- 坏 tool_call 防御（名称不存在 / 参数非法 → 错误回灌 → 2 次强制收敛）
- 最大轮次限制（MAX_ROUNDS 后强制无工具回答）
- process_trace 过程追踪（tool_call / tool_result / tool_error / agent_done）
- L1 工作记忆管理（manage_l1_context 逐出）
- 工具并行执行（asyncio.gather + Semaphore 限单轮并发）
- 中间轮 JUDGE_MODEL（flash 快）/ 最终轮 CHAT_MODEL

决策依据：spec T16, 风险与缓解表。
"""

import asyncio
import hashlib
import json
import logging
import time
from collections import Counter
from dataclasses import dataclass, field
from typing import Awaitable, Callable
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.database import AsyncSessionLocal
from services.rag.pipeline import (
    LLMToolResponse,
    ToolCall,
    llm_generate_with_tools,  # noqa: F401 — 保留模块属性供测试 patch（mock 目标）
    llm_generate_with_tools_stream,
)
from services.react_agent.memory import assemble_system_prompt, manage_l1_context
from services.react_agent.tools import (
    get_agent_schemas,  # noqa: F401 — 保留模块属性供测试 patch（mock 目标）
    get_tool_by_name,
    get_tools_for_agent,
)
from services.react_agent.tools.base import (
    ApprovalRequired,
    Tool,
    ToolFailed,
    ToolRetryError,
)
from services.token_quota import check_quota

logger = logging.getLogger(__name__)

# ── 常量 ──────────────────────────────────────────────────────
MAX_ROUNDS = settings.REACT_MAX_TOOL_ROUNDS  # Spec A#6: 6 轮工具上限（config 可调）
# A3 契约化：per-tool 重试预算（借鉴 pydantic-ai _check_max_retries）——
# 同一工具连续失败超限即终止本轮，成功一次即清零
MAX_TOOL_RETRIES = 3
AGENT_CONCURRENCY_LIMIT = 5
# 工具实际执行墙钟超时（秒）：工具内部外部 API（embedding/rerank/LLM/网络）挂起时
# 兜底超时降级，避免「调用工具后永久卡住」只能等会话级 REACT_MAX_DURATION_SEC 强断。
# 按工具差异化：深度 agentic 工具（多轮 LLM + Reflexion 循环）正常就需要 >60s，
# 一刀切 60s 会误杀（如 answer_from_index 实测 ~58s+）。轻量检索工具保持短超时防真卡。
DEFAULT_TOOL_EXEC_TIMEOUT_SEC = 60
LONG_TOOL_EXEC_TIMEOUT_SEC = 150  # 需 < REACT_MAX_DURATION_SEC(180)，留会话级余量
LONG_EXEC_TOOLS = {
    "answer_from_index",  # 深度 agentic RAG：改写→检索→重排→生成→反思（≤2 轮）
    "interview_coach",    # 多轮模拟面试（一问一答推进）
    "jd_match",           # 简历×JD LLM 匹配 + 6-block 报告
    "diagnose_resume",    # 多维度简历诊断
    "rewrite_resume",     # 整份简历重写
    "rewrite_star",       # STAR 逐条改写
    "translate",          # 中英文互译
}


def _tool_exec_timeout(tool_name: str) -> float:
    """取工具执行超时：深度工具给足时间，其余用默认短超时防外部 API 挂起。"""
    return (
        LONG_TOOL_EXEC_TIMEOUT_SEC
        if tool_name in LONG_EXEC_TOOLS
        else DEFAULT_TOOL_EXEC_TIMEOUT_SEC
    )

# 中间轮用 JUDGE_MODEL（flash 快），最终轮用 CHAT_MODEL
MIDDLE_MODEL = "judge"
FINAL_MODEL = None  # None → 默认 CHAT_MODEL

# ── M3 OpenManus 借鉴：next_step_prompt + is_stuck 防卡死 ──
# next_step_prompt：每轮 LLM 调用前注入引导，收敛重复工具调用 / 引导直接回答
NEXT_STEP_PROMPT = (
    "如果你已经获得足够的信息可以直接回答用户的问题，请直接给出最终回答，"
    "不要再调用工具。如需继续调用工具，请优先尝试新的搜索词或工具参数。"
)
# is_stuck：监测到重复 tool_call 后注入的换策略提示（不终止循环）
STUCK_PROMPT = (
    "检测到你最近几轮在重复执行相同的工具调用，可能陷入了循环。"
    "请停止重复当前操作，换一种完全不同的策略或参数，或者直接基于已有信息回答用户。"
)
STUCK_WINDOW = 3  # 回溯窗口：最近 N 轮
STUCK_THRESHOLD = 2  # 签名重复 ≥2 次判为 stuck

# ── 工具结果预算管理（借鉴 Hermes budget_for_context_window）──
# 单个工具结果回灌 LLM 前的预算上限（字符数）。超出预算的结果被截断，
# 避免单一超长工具结果（如整份简历/批量搜索）挤爆 L1 上下文窗口。
# 预算随上下文窗口大小自适应：窗口越大，允许的单结果预算越高。
DEFAULT_CONTEXT_WINDOW = 16384  # 对应 L1 预算（memory.DEFAULT_L1_BUDGET）
TOOL_RESULT_BUDGET_CHARS = 6000  # 16384 窗口下的默认单结果字符预算
_TOOL_RESULT_BUDGET_STEP = 2000  # 每提升一档窗口，预算增加量


def _tool_result_budget(context_window: int | None = None) -> int:
    """根据上下文窗口大小返回工具结果预算（字符数）。

    - context_window=None → 用默认 L1 预算档位
    - 窗口越大 → 预算越高（线性增量），始终有下限 4000、上限 20000
    """
    window = context_window if context_window else DEFAULT_CONTEXT_WINDOW
    budget = TOOL_RESULT_BUDGET_CHARS + max(0, window - DEFAULT_CONTEXT_WINDOW) // 8192 * _TOOL_RESULT_BUDGET_STEP
    return max(4000, min(budget, 20000))

# ── D1 工具审批门（借鉴 pydantic-ai Deferred tools）──
# 命中 requires_approval 的工具执行前需用户确认；SSE 单向流，
# 决议经独立端点回传（api/qa.py POST /qa/approval）。
APPROVAL_TIMEOUT_SEC = 120  # 审批挂起超时（秒）；超时按拒绝处理，避免无响应挂死

# ── D3 空输出重试预算（与 A3 tool_retries 分离的独立计数器）──
# 模型连续 N 次「空 content + 无 tool_calls」即直接收敛，不占用工具重试预算。
OUTPUT_RETRY_LIMIT = 2

# ── D2 失败分类定向恢复（借鉴 tau-bench fault_type）──
# 按最近一次失败类型选择 stuck 换策略提示；未分类回退现有 STUCK_PROMPT。
_FAULT_TYPE_HINTS: dict[str, str] = {
    "used_wrong_tool": (
        "检测到你最近几轮执行受阻。你可能用错了工具——请换一个更合适的工具，"
        "或直接基于已有信息回答用户。"
    ),
    "used_wrong_tool_argument": (
        "检测到你最近几轮执行受阻。请检查工具参数是否正确（如 resume_id、查询词、指令），"
        "修正后重试，或直接基于已有信息回答用户。"
    ),
    "user_info_missing": (
        "检测到你最近几轮执行受阻。当前缺少完成任务所需的用户信息，"
        "请先向用户澄清需求（明确缺什么），或直接回答已知部分。"
    ),
}

# D1 审批注册表：approval_id → 待审批条目（同进程内，uvicorn 单进程假设）。
# 决议端点（api/qa.py）通过 resolve_approval 解析；loop 通过 wait_for_approval 挂起。
class _ApprovalEntry:
    __slots__ = ("user_id", "event", "decision")

    def __init__(self, user_id: int) -> None:
        self.user_id = user_id
        self.event: asyncio.Event = asyncio.Event()
        self.decision: str | None = None


_approval_registry: dict[str, _ApprovalEntry] = {}


# ── M3 增强：结构化工具调用记录 + 多模式循环检测 ──────────────
# 相比旧方案（简单签名重复 ≥2 次），新增：
# - 结构化调用记录（ToolCallRecord）：记录工具名、参数哈希、结果哈希、时间戳等，
#   为后续审计和调试提供完整调用链路信息。
# - 交替模式检测（A→B→A→B）：旧方案只检测相同签名重复，无法识别交替循环。
# - 分级响应（critical/warning）：critical 级别强制终止循环避免烧 token，
#   warning 级别注入换策略提示允许模型自愈。


@dataclass
class ToolCallRecord:
    """工具调用记录，结构化存储单次调用的关键信息。"""

    tool_name: str
    args_hash: str
    tool_call_id: str
    run_id: str | None = None
    outcome_kind: str | None = None  # "success" | "error" | "tool-loop-veto"
    result_hash: str | None = None
    timestamp: float = 0.0


class ToolLoopDetector:
    """工具循环检测器，支持相同调用重复检测 + 交替模式检测 + 分级响应。

    设计思路：
    - window：回溯窗口大小，保留最近 N 条调用记录（默认 5，覆盖 3+ 轮循环）
    - critical_threshold：相同调用重复 ≥ N 次 → critical（强制终止，避免烧 token）
    - warning_threshold：相同调用重复 ≥ N 次 → warning（注入换策略提示，允许自愈）
    - 交替模式检测：A→B→A→B 模式 → warning（旧方案无法识别此类循环）
    - 干预后 clear()：模型换策略成功后清空历史，重新计数
    """

    def __init__(
        self,
        window: int = 5,
        critical_threshold: int = 3,
        warning_threshold: int = 2,
    ):
        self.window = window
        self.critical_threshold = critical_threshold
        self.warning_threshold = warning_threshold
        self.history: list[ToolCallRecord] = []

    def record(
        self, tool_name: str, args: dict, tool_call_id: str
    ) -> ToolCallRecord:
        """记录一次工具调用，超出窗口自动淘汰最旧记录。"""
        args_hash = hashlib.md5(
            json.dumps(args, sort_keys=True).encode()
        ).hexdigest()[:8]
        record = ToolCallRecord(
            tool_name=tool_name,
            args_hash=args_hash,
            tool_call_id=tool_call_id,
            timestamp=time.time(),
        )
        self.history.append(record)
        # 维护滑动窗口，淘汰最旧记录
        if len(self.history) > self.window:
            self.history.pop(0)
        return record

    def update_outcome(
        self,
        record: ToolCallRecord,
        *,
        outcome_kind: str,
        result_hash: str | None = None,
    ) -> None:
        """更新调用记录的执行结果（成功/失败/被 veto）。"""
        record.outcome_kind = outcome_kind
        if result_hash:
            record.result_hash = result_hash

    def detect_loop(self) -> dict:
        """检测循环模式，返回 {stuck: bool, level: "critical"|"warning"|None, reason: str}。

        检测策略（按优先级）：
        1. 相同调用重复检测（critical）：同一工具+相同参数在窗口内出现 ≥ critical_threshold 次
        2. 交替模式检测（warning）：A→B→A→B 模式在窗口内出现
        """
        if len(self.history) < 2:
            return {"stuck": False, "level": None, "reason": ""}

        # 检测策略 1：相同调用重复（critical 级别）
        sig_counts = Counter(
            (r.tool_name, r.args_hash) for r in self.history
        )
        for sig, count in sig_counts.items():
            if count >= self.critical_threshold:
                return {
                    "stuck": True,
                    "level": "critical",
                    "reason": f"工具 {sig[0]} 以相同参数重复调用 {count} 次",
                }
            if count >= self.warning_threshold:
                return {
                    "stuck": True,
                    "level": "warning",
                    "reason": f"工具 {sig[0]} 以相同参数调用 {count} 次",
                }

        # 检测策略 2：交替模式 A→B→A→B（warning 级别）
        if len(self.history) >= 4:
            names = [r.tool_name for r in self.history[-4:]]
            if (
                names[0] == names[2]
                and names[1] == names[3]
                and names[0] != names[1]
            ):
                return {
                    "stuck": True,
                    "level": "warning",
                    "reason": f"检测到交替调用模式: {names[0]} → {names[1]} → {names[0]} → {names[1]}",
                }

        return {"stuck": False, "level": None, "reason": ""}

    def clear(self) -> None:
        """清空历史（干预后调用，重新计数）。"""
        self.history.clear()


def _pick_stuck_hint(fault_type: str | None) -> str:
    """D2: 按最近 fault_type 选择 stuck 换策略提示；未分类回退现有 STUCK_PROMPT。"""
    if not fault_type:
        return STUCK_PROMPT
    return _FAULT_TYPE_HINTS.get(fault_type, STUCK_PROMPT)


# ── P1-3: 回合 checkpoint（崩溃/断连恢复续答）────────────────
# 每轮工具执行后把 messages 快照存 Redis（TTL 短），正常结束清除。
# 下次同 resume 同问题提问时，若 checkpoint 未过期则从断点续跑，
# 不再重跑已完成的工具（省 token）。key 由 streaming 层注入。


async def _save_react_checkpoint(
    key: str,
    question: str,
    messages: list[dict],
    ttl_seconds: int,
) -> None:
    """存回合 checkpoint 到 Redis（best-effort，失败不影响主流程）。"""
    try:
        from core.redis_client import get_redis

        redis = await get_redis()
        if redis is None:
            return
        payload = {
            "question": question,
            "messages": messages,
        }
        await redis.setex(
            key, ttl_seconds, json.dumps(payload, ensure_ascii=False)
        )
    except Exception:
        logger.debug("保存回合 checkpoint 失败（忽略）", exc_info=True)


async def _load_react_checkpoint(
    key: str,
    question: str,
) -> list[dict] | None:
    """读回合 checkpoint；仅当问题与上次一致时返回 messages（best-effort）。"""
    try:
        from core.redis_client import get_redis

        redis = await get_redis()
        if redis is None:
            return None
        raw = await redis.get(key)
        if not raw:
            return None
        data = json.loads(raw)
        if data.get("question") != question:
            return None
        messages = data.get("messages")
        if not isinstance(messages, list) or not messages:
            return None
        logger.info("恢复回合 checkpoint: key=%s (%d 条消息)", key, len(messages))
        return messages
    except Exception:
        logger.debug("读取回合 checkpoint 失败（忽略）", exc_info=True)
        return None


async def _clear_react_checkpoint(key: str) -> None:
    """回合正常结束清除 checkpoint（best-effort）。"""
    try:
        from core.redis_client import get_redis

        redis = await get_redis()
        if redis is None:
            return
        await redis.delete(key)
    except Exception:
        logger.debug("清除回合 checkpoint 失败（忽略）", exc_info=True)


# ── P1-2: 回合中注入（用户在 agent 思考期间追加消息）────────────────
# 前端经 POST /qa/inject 把追加消息写入 Redis list（inject_key），
# react_loop 每轮 LLM 调用前 drain 并入 messages。回合结束删除队列。
# 用 Redis list 的 LPUSH/RPOP 实现 FIFO；不依赖 list TTL（回合结束清理），
# 断连残留的未消费消息由同 key 的下一回合复用（可接受，append 语义）。


async def _enqueue_injection(key: str, content: str) -> bool:
    """把用户追加消息写入回合注入队列（best-effort）。"""
    try:
        from core.redis_client import get_redis

        redis = await get_redis()
        if redis is None:
            return False
        # InMemoryRedis 需支持 lpush/rpop；不支持时静默降级（不注入）
        if not hasattr(redis, "lpush"):
            return False
        await redis.lpush(key, content)
        return True
    except Exception:
        logger.debug("写入回合注入队列失败（忽略）", exc_info=True)
        return False


async def _drain_injections(key: str, max_items: int = 2) -> list[str]:
    """弹出回合注入队列中的追加消息（FIFO，最多 max_items 条）。"""
    try:
        from core.redis_client import get_redis

        redis = await get_redis()
        if redis is None or not hasattr(redis, "rpop"):
            return []
        items: list[str] = []
        for _ in range(max_items):
            raw = await redis.rpop(key)
            if raw is None:
                break
            items.append(str(raw))
        return items
    except Exception:
        logger.debug("读取回合注入队列失败（忽略）", exc_info=True)
        return []


def register_approval(approval_id: str, user_id: int) -> None:
    """D1: 注册一个待审批请求到内存注册表。"""
    _approval_registry[approval_id] = _ApprovalEntry(user_id)


def resolve_approval(approval_id: str, user_id: int, decision: str) -> bool:
    """D1: 决议端点调用——解析审批请求。

    返回 False 表示请求不存在 / 不属于该用户 / 已被解析（幂等拒绝）。
    """
    entry = _approval_registry.get(approval_id)
    if entry is None or entry.user_id != user_id or entry.event.is_set():
        return False
    entry.decision = decision
    entry.event.set()
    return True


def drop_approval(approval_id: str) -> None:
    """D1: 清理审批注册表条目（wait_for_approval 结束或异常时兜底）。"""
    _approval_registry.pop(approval_id, None)


async def wait_for_approval(approval_id: str, timeout: float = APPROVAL_TIMEOUT_SEC) -> str:
    """D1: 挂起等待前端审批决议（approval_request 已发射后调用）。

    决议端点 resolve_approval 放行 asyncio.Event → 返回 "approved" / "denied"。
    超时按拒绝处理（避免用户不响应导致 Agent 无限挂起）；结束后清理注册表。
    """
    entry = _approval_registry.get(approval_id)
    if entry is None:
        return "denied"
    try:
        await asyncio.wait_for(entry.event.wait(), timeout=timeout)
        return entry.decision or "denied"
    except asyncio.TimeoutError:
        logger.warning("审批超时（%ss），按拒绝处理: approval_id=%s", timeout, approval_id)
        return "denied"
    finally:
        drop_approval(approval_id)


# ── 审批增强（借鉴 OpenClaw allow-always + severity）──────────────
# 用户对某工具选择"始终允许"后，记录到 Redis（TTL 7 天），后续同工具
# 审批请求自动放行，减少重复弹窗。best-effort：Redis 不可用降级为不记忆。

_APPROVAL_MEMORY_TTL_SEC = 7 * 24 * 3600  # 7 天


async def remember_tool_approval(user_id: int, tool_name: str) -> None:
    """记录用户"始终允许"该工具（best-effort，失败不影响审批流程）。"""
    try:
        from core.redis_client import get_redis

        redis = await get_redis()
        if redis is None:
            return
        key = f"react:approval:{user_id}:{tool_name}"
        await redis.setex(key, _APPROVAL_MEMORY_TTL_SEC, "1")
    except Exception:
        logger.debug("记录 allow-always 审批偏好失败（忽略）", exc_info=True)


async def check_tool_approval(user_id: int, tool_name: str) -> bool:
    """检查用户是否"始终允许"该工具（命中则后续自动放行）。"""
    try:
        from core.redis_client import get_redis

        redis = await get_redis()
        if redis is None:
            return False
        key = f"react:approval:{user_id}:{tool_name}"
        return bool(await redis.get(key))
    except Exception:
        return False


@dataclass
class ReactLoopResult:
    """ReAct 循环返回值。"""

    answer: str
    process_trace: list[dict] = field(default_factory=list)
    usage: dict = field(default_factory=lambda: {"prompt_tokens": 0, "completion_tokens": 0})
    sources: list[dict] = field(default_factory=list)  # Spec A#10: search_resume 来源去重
    db_trace: dict = field(default_factory=dict)  # Spec 行 459: 完整 prompt 进 DB
    # T17.1: checkpoint 恢复标记——streaming 层据此注入中断提示 + 恢复用户消息
    checkpoint_restored: bool = False


# 工具并行执行 Semaphore（Spec A#32：限单轮工具并发，非整个 Agent 循环）
_tool_semaphore: asyncio.Semaphore | None = None


def _get_tool_semaphore() -> asyncio.Semaphore:
    """懒加载工具执行 Semaphore（绑定到当前 event loop）。"""
    global _tool_semaphore
    if _tool_semaphore is None:
        _tool_semaphore = asyncio.Semaphore(AGENT_CONCURRENCY_LIMIT)
    return _tool_semaphore


async def react_loop(
    db: AsyncSession,
    user_id: int,
    resume_id: int,
    question: str,
    *,
    history: list[dict] | None = None,
    event_callback: Callable[[dict], Awaitable[None]] | None = None,
    tool_mode: str = "agent",
    checkpoint_key: str | None = None,
    checkpoint_ttl_seconds: int = 300,
    inject_key: str | None = None,
) -> ReactLoopResult:
    """ReAct 核心循环。

    流程：
    1. 配额预检 → 不足则直接返回
    2. 装配 system prompt（L2/L3 记忆注入）
    3. 循环调用 LLM with tools（≤ MAX_ROUNDS 轮）
       - 无 tool_call → 直接返回
       - 有 tool_call → 执行 → 结果/错误回灌 → 继续
       - 2 次连续坏调用 → 跳出循环强制收敛
    4. 强制收敛：无工具调用 → 返回答案

    Args:
        db: 数据库会话
        user_id: 用户 ID
        resume_id: 简历 ID
        question: 用户问题
        history: 可选的额外历史消息（L2 已在 system prompt 装配，
                 此参数用于多轮对话延续）
        event_callback: 可选的异步事件回调，每次 process_trace 事件
                       （tool_call/tool_result/tool_error/agent_done/quota_exceeded）
                        产生时调用，供 streaming 层实时推送 SSE 事件

    Returns:
        ReactLoopResult: answer + process_trace + usage
    """
    process_trace: list[dict] = []
    total_usage = {"prompt_tokens": 0, "completion_tokens": 0}
    all_sources: list[dict] = []  # Spec A#10: 聚合 search_resume 来源
    db_rounds: list[dict] = []  # Spec 行 459: 每轮 prompt 信息（完整 prompt 进 DB）

    async def _emit(event: dict) -> None:
        """写入 process_trace 并调用事件回调（供 streaming 层使用）。

        tool_stream / answer_token 为逐 token（分块）高频透传事件，只推前端、
        不入 process_trace，避免撑爆事件日志与 agent_done 的紧凑 trace。
        """
        if event.get("type") not in ("tool_stream", "answer_token"):
            process_trace.append(event)
        if event_callback:
            await event_callback(event)

    async def _emit_llm_events(resp: LLMToolResponse) -> None:
        """LLM 调用后推 usage 事件（Spec A#28）。

        reasoning_content 已在流式调用中逐段 emit 为 agent_thought，此处只推 usage。
        """
        await _emit(
            {
                "type": "usage",
                "usage": dict(resp.usage),
                "total": dict(total_usage),
            }
        )

    # 0. 分阶段耗时追踪（定位 agent 交互瓶颈，只打日志不改行为）
    _t0 = time.perf_counter()
    _phases: dict[str, float] = {}

    def _log_agent_timing(tag: str) -> None:
        _phases["total_ms"] = round((time.perf_counter() - _t0) * 1000)
        logger.info("agent_timing tag=%s phases=%s", tag, _phases)

    # 1. 配额预检
    allowed, quota_msg = await check_quota(user_id)
    if not allowed:
        await _emit({"type": "quota_exceeded", "message": quota_msg})
        return ReactLoopResult(
            answer=quota_msg or "今日额度已用完，请明天再试。",
            process_trace=process_trace,
            usage=total_usage,
            sources=[],
            db_trace={"system_prompt": "", "rounds": [], "total_rounds": 0},
        )

    # T17 优化② 问候/感谢零 LLM 快路径（agent1 + builder 通用）：
    # 放在 system prompt 装配之前——问候不需要 L2/L3/L4，模板直接秒回。
    from services.react_agent.tool_gate import greeting_reply, is_trivial_greeting

    if is_trivial_greeting(question):
        reply = greeting_reply(question)
        await _emit({"type": "agent_done", "content": reply})
        _log_agent_timing("greeting")
        return ReactLoopResult(
            answer=reply,
            process_trace=process_trace,
            usage=total_usage,
            sources=[],
            db_trace=_build_db_trace("", [], FINAL_MODEL),
        )

    # 2. 装配 system prompt（L2 历史 + L3 画像 + L4 记忆注入；builder 模式用允许生成的专属指令）
    _phases["prompt_assembly_ms"] = round((time.perf_counter() - _t0) * 1000)
    # P2-9：history（多轮完整轮次）已作为 user/assistant 消息注入 messages，
    # 其 question 集合传给 L2 摘要做排除，避免同一历史双重携带。
    _injected_questions: set[str] = set()
    if history:
        for msg in history:
            if msg.get("role") == "user" and msg.get("content"):
                _injected_questions.add(str(msg["content"]))
    system_prompt = await assemble_system_prompt(
        db,
        user_id,
        resume_id,
        builder=(tool_mode == "builder"),
        query=question,
        exclude_questions=_injected_questions or None,
    )
    _phases["prompt_assembly_ms"] = round((time.perf_counter() - _t0) * 1000)

    # 3. 初始化消息
    messages: list[dict] = [
        {"role": "system", "content": system_prompt},
    ]
    if history:
        messages.extend(history)
    messages.append({"role": "user", "content": question})

    # P1-3：回合 checkpoint 恢复——若存在未过期且问题一致的 checkpoint
    # （上次回合中断/断连留下），从断点续跑，不重跑已完成的工具。
    # 恢复的消息含上次的 system prompt + 历史 + 已执行工具结果。
    restored_from_checkpoint = False
    if checkpoint_key:
        checkpoint_messages = await _load_react_checkpoint(checkpoint_key, question)
        if checkpoint_messages:
            messages = checkpoint_messages
            restored_from_checkpoint = True
            # 恢复后清理（本次续跑若再中断会重新存）
            await _clear_react_checkpoint(checkpoint_key)
            # T25: 中断消息注入（借鉴 OpenClaw turn_aborted）——恢复时 LLM 感知
            # 上一轮被中断、后台进程/工具可能部分执行，避免"当作全新会话"误答。
            # 插入到 system prompt 之后（第 0 条之后）。
            insert_at = 1
            for i, m in enumerate(messages):
                if m.get("role") == "system":
                    insert_at = i + 1
                    break
            messages.insert(
                insert_at,
                {
                    "role": "system",
                    "content": (
                        "<turn_aborted>\n上一轮对话被中断，已从断点续跑。任何正在运行"
                        "的后台进程可能仍在活动；已执行的工具可能部分完成。"
                        "请结合已有上下文继续处理，必要时补充查询/调用工具。\n"
                        "</turn_aborted>"
                    ),
                },
            )
            logger.info(
                "回合 checkpoint 恢复+中断提示注入: user=%d resume=%d messages=%d",
                user_id, resume_id, len(messages),
            )

    # 4. 获取工具 schemas（v2: 统一使用 unified 工具集 + 相关性过滤）
    from services.react_agent.tool_gate import filter_agent_tools

    agent_tools = filter_agent_tools(question, get_tools_for_agent())
    tool_schemas = [tc().to_openai_schema() for tc in agent_tools]

    # D1/D2/D3 循环级状态（置于 builder 意图直达之前——该路径也会执行工具，需要审批锁）
    # D1 审批门：本轮审批串行化锁（同一轮并行工具的审批请求逐个处理，前端一次只弹一个）
    approval_lock = asyncio.Lock()
    # D3 空输出重试预算（独立计数器，不占用 A3 tool_retries 预算）
    output_empty_rounds = 0
    # D2 最近一次失败分类（stuck 时按此选变体换策略提示）
    recent_fault_type: str | None = None

    # T17 优化① builder 意图直达：跳过 ReAct「决定轮」，直接执行解析出的工具。
    # 编辑器命令明确（生成/检查/修改 X 模块），一次操作从 3 轮 LLM 压到 1 次工具调用。
    if tool_mode == "builder":
        from services.react_agent.builder_intent import resolve_builder_intent

        intent = await resolve_builder_intent(question, user_id=user_id)
        if intent:
            tool_name, tool_args = intent
            tool_args["resume_id"] = resume_id
            tc = ToolCall(
                id="intent_direct",
                name=tool_name,
                arguments=json.dumps(tool_args, ensure_ascii=False),
            )
            await _emit(
                {"type": "tool_call", "name": tool_name, "arguments": tc.arguments, "id": tc.id}
            )
            tool_semaphore = _get_tool_semaphore()
            result, is_error, sources, _tool_usage = await _execute_tool_call_with_limit(
                tc,
                user_id,
                tool_semaphore,
                emit=_emit,
                approval_lock=approval_lock,
                round_no=1,
            )
            await _emit(
                {
                    "type": "tool_result" if not is_error else "tool_error",
                    "name": tool_name,
                    "result": result[:2000],
                    "id": tc.id,
                    "error": result if is_error else None,
                }
            )
            await _emit({"type": "agent_done", "content": result})
            _phases["intent_tool_ms"] = round((time.perf_counter() - _t0) * 1000)
            _log_agent_timing("intent")
            if checkpoint_key:
                await _clear_react_checkpoint(checkpoint_key)
            return ReactLoopResult(
                answer=result,
                process_trace=process_trace,
                usage=total_usage,
                sources=_deduplicate_sources(sources),
                db_trace=_build_db_trace(system_prompt, [], FINAL_MODEL),
                checkpoint_restored=restored_from_checkpoint,
            )

    # 5. ReAct 循环
    # A3: per-tool 重试预算（同一工具连续失败计数，成功清零）替代全局连续计数
    tool_retries: dict[str, int] = {}
    rounds = 0
    _llm_round_ms = 0.0
    _tool_exec_ms = 0.0
    # M3 增强：ToolLoopDetector 替代旧方案的 recent_round_signatures
    # 支持交替模式检测 + 分级响应（critical 强制终止 / warning 注入提示）
    loop_detector = ToolLoopDetector()
    stuck = False
    stuck_level: str | None = None  # "critical" | "warning" | None

    while rounds < MAX_ROUNDS:
        rounds += 1

        # DeepInterview SessionGuard 对照：会话墙钟总时长上限（防模型循环/上游慢失控烧 token）
        if time.perf_counter() - _t0 > settings.REACT_MAX_DURATION_SEC:
            msg = "会话时长已达上限，请重试。"
            await _emit({"type": "agent_done", "content": msg})
            logger.warning(
                "ReAct 会话超时（%ss）强制结束: user=%d resume=%d rounds=%d",
                settings.REACT_MAX_DURATION_SEC,
                user_id,
                resume_id,
                rounds,
            )
            return ReactLoopResult(
                answer=msg,
                process_trace=process_trace,
                usage=total_usage,
                sources=_deduplicate_sources(all_sources),
                db_trace=_build_db_trace(system_prompt, db_rounds),
                checkpoint_restored=restored_from_checkpoint,
            )

        # 每轮 LLM 调用前复查配额（Spec A#5：超限立即停止）
        if rounds > 1:
            allowed, quota_msg = await check_quota(user_id)
            if not allowed:
                await _emit({"type": "quota_exceeded", "message": quota_msg})
                return ReactLoopResult(
                    answer=quota_msg or "今日额度已用完，请明天再试。",
                    process_trace=process_trace,
                    usage=total_usage,
                    sources=_deduplicate_sources(all_sources),
                    db_trace=_build_db_trace(system_prompt, db_rounds),
                    checkpoint_restored=restored_from_checkpoint,
                )

        # L1 上下文管理（逐出旧轮次，截断工具结果）
        messages = manage_l1_context(messages)

        # T25: 压缩后恢复用户原始问题（Hermes 借鉴）——L1 结构化压缩可能把
        # 用户消息顶成摘要 handoff，末尾恢复确保模型不"答非所问"。幂等：question
        # 已存在于消息列表（任何位置）则跳过，避免 L1 未逐出时重复注入。
        if not any(
            m.get("role") == "user" and m.get("content") == question
            for m in messages
        ):
            messages.append({"role": "user", "content": question})

        # P1-2：回合中注入——用户在 agent 思考期间追加的消息并入当前回合
        # （FIFO，每轮最多 2 条）。让 agent 感知"追问/补充"，无需等回合结束。
        if inject_key:
            injections = await _drain_injections(inject_key)
            if injections:
                for inj in injections:
                    messages.append({"role": "user", "content": inj})
                    await _emit(
                        {"type": "injection", "content": inj}
                    )
                logger.info(
                    "回合中注入 %d 条追加消息: user=%d rounds=%d",
                    len(injections), user_id, rounds,
                )

        # M3 next_step_prompt：第 2 轮起每轮 LLM 调用前注入引导（收敛/换策略）。
        # stuck 时注入换策略提示覆盖默认引导；注入后重置标志（下一轮重新检测）。
        # D2: stuck 提示按最近失败分类（fault_type）选变体，未分类回退现有 STUCK_PROMPT。
        # M3 增强：critical 级别不注入提示，直接 break 强制收敛（避免烧 token）。
        if rounds > 1:
            if stuck:
                if stuck_level == "critical":
                    # critical 级别：不再注入提示，直接跳出循环走强制收敛
                    break
                hint = _pick_stuck_hint(recent_fault_type) + "\n" + NEXT_STEP_PROMPT
                stuck = False
                stuck_level = None
                # 注入后清空检测历史：避免当轮结尾又立即判 stuck，
                # 保证模型恢复不同调用后不再连续注入换策略提示（注入即视为已干预）。
                loop_detector.clear()
            else:
                hint = NEXT_STEP_PROMPT
            messages.append({"role": "user", "content": hint})

        # 调用 LLM（中间轮用 JUDGE_MODEL = flash，流式：推理过程实时推给前端）
        _llm_round_start = time.perf_counter()
        response = await _stream_middle_round(
            messages=messages,
            tools=tool_schemas,
            user_id=user_id,
            model=MIDDLE_MODEL,
            emit=_emit,
        )
        _llm_round_ms += (time.perf_counter() - _llm_round_start) * 1000
        _phases["llm_rounds_ms"] = round(_llm_round_ms)

        _accumulate_usage(total_usage, response)
        await _emit({"type": "usage", "usage": dict(response.usage), "total": dict(total_usage)})

        # D3: 模型产出内容或有 tool_call 即视为「非空输出」，重置空输出计数器
        if response.tool_calls or (response.content or "").strip():
            output_empty_rounds = 0

        # 无 tool_call → 直接回答
        if not response.tool_calls:
            content = (response.content or "").strip()
            # D3 独立空输出重试预算：连续「空 content + 无 tool_calls」达限直接收敛，
            # 提示用户简化问题；与 A3 tool_retries（工具重试预算）完全分离。
            if not content:
                output_empty_rounds += 1
                if output_empty_rounds >= OUTPUT_RETRY_LIMIT:
                    msg = "模型连续多次未产出结果，请简化问题重试。"
                    logger.warning(
                        "ReAct 连续 %d 次空输出，收敛: user=%d resume=%d",
                        output_empty_rounds,
                        user_id,
                        resume_id,
                    )
                    await _emit({"type": "agent_done", "content": msg})
                    _log_agent_timing("empty_converged")
                    if checkpoint_key:
                        await _clear_react_checkpoint(checkpoint_key)
                    return ReactLoopResult(
                        answer=msg,
                        process_trace=process_trace,
                        usage=total_usage,
                        sources=_deduplicate_sources(all_sources),
                        db_trace=_build_db_trace(system_prompt, db_rounds, FINAL_MODEL),
                        checkpoint_restored=restored_from_checkpoint,
                    )
                logger.warning(
                    "ReAct 空输出（第 %d 次连续），注入提示继续: user=%d rounds=%d",
                    output_empty_rounds,
                    user_id,
                    rounds,
                )
                # 提示模型直接作答，继续下一轮（不 return）
                messages.append(
                    {
                        "role": "user",
                        "content": "你尚未产出任何回答内容。请直接给出最终回答，不要调用工具。",
                    }
                )
                continue

            # 正常回答
            await _emit({"type": "agent_done", "content": content})
            _log_agent_timing("done")
            if checkpoint_key:
                await _clear_react_checkpoint(checkpoint_key)
            return ReactLoopResult(
                answer=content,
                process_trace=process_trace,
                usage=total_usage,
                sources=_deduplicate_sources(all_sources),
                db_trace=_build_db_trace(system_prompt, db_rounds, FINAL_MODEL),
                checkpoint_restored=restored_from_checkpoint,
            )

        # 有 tool_call → 并行执行工具（Spec A#21: asyncio.gather）
        messages.append(_build_assistant_message(response))

        # 先发所有 tool_call 事件（让用户立刻看到 Agent 在调哪些工具）
        for tc in response.tool_calls:
            await _emit(
                {
                    "type": "tool_call",
                    "name": tc.name,
                    "arguments": tc.arguments,
                    "id": tc.id,
                }
            )

        # 并行执行所有工具（Spec A#32: Semaphore 限单轮并发）
        # D1: 传入本轮 approval_lock 串行化审批请求 + round_no 供 approval_request 展示
        tool_semaphore = _get_tool_semaphore()
        _tool_start = time.perf_counter()
        results = await asyncio.gather(
            *[
                _execute_tool_call_with_limit(
                    tc,
                    user_id,
                    tool_semaphore,
                    emit=_emit,
                    approval_lock=approval_lock,
                    round_no=rounds,
                )
                for tc in response.tool_calls
            ]
        )
        _tool_exec_ms += (time.perf_counter() - _tool_start) * 1000
        _phases["tool_exec_ms"] = round(_tool_exec_ms)

        # 记录本轮 prompt 信息到 db_rounds（Spec 行 459: 完整 prompt 进 DB）
        db_round: dict = {
            "round": rounds,
            "model": MIDDLE_MODEL,
            "tool_calls": [
                {"name": tc.name, "arguments": tc.arguments, "id": tc.id}
                for tc in response.tool_calls
            ],
            "tool_results": [],
        }
        db_rounds.append(db_round)

        # 处理结果：发 tool_result/tool_error 事件 + 回灌 messages + 收集 sources + 累计工具 LLM usage
        all_bad = True
        for tc, (tool_result, is_error, tool_sources, tool_usage) in zip(
            response.tool_calls, results
        ):
            if is_error:
                await _emit(
                    {
                        "type": "tool_error",
                        "name": tc.name,
                        "error": tool_result,
                        "id": tc.id,
                    }
                )
            else:
                await _emit(
                    {
                        "type": "tool_result",
                        "name": tc.name,
                        "result": tool_result,
                        "id": tc.id,
                    }
                )
                all_bad = False

            # 累计工具内部 LLM 调用的 token 消耗到主 usage（builder 工具内部有独立 LLM 调用）
            _accumulate_usage(total_usage, tool_usage)

            # 收集工具来源（Spec A#10: search_resume 来源聚合）
            all_sources.extend(tool_sources)

            # tool 结果/错误回灌到 messages（工具结果预算管理：超长结果截断到
            # 预算上限，避免单一超长结果挤爆 L1 上下文窗口）
            budget = _tool_result_budget()
            content = tool_result
            if len(content) > budget:
                content = content[: budget - 3] + "..."
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": content,
                }
            )

            # 记录工具结果到 db_round（截断避免 DB 膨胀）
            db_round["tool_results"].append(
                {
                    "name": tc.name,
                    "result": tool_result[:500],
                    "is_error": is_error,
                }
            )

        # 工具执行完毕后推送累计 usage（含工具内部 LLM 消耗），让前端实时更新 token 计数
        await _emit({"type": "usage", "usage": dict(total_usage), "total": dict(total_usage)})

        # P1-3：本轮工具执行完成 → 存 checkpoint（中断/断连后可从断点续跑）
        if checkpoint_key:
            await _save_react_checkpoint(
                checkpoint_key, question, messages, checkpoint_ttl_seconds
            )

        # A3: per-tool 重试预算——同一工具连续失败超限即终止本轮（避免烧 token 反复重试同一错误）
        # 借鉴 pydantic-ai：retries[tool_name] 记账 + _check_max_retries 超限终止
        if all_bad:
            exceeded = False
            for tc in response.tool_calls:
                tool_retries[tc.name] = tool_retries.get(tc.name, 0) + 1
                if tool_retries[tc.name] >= MAX_TOOL_RETRIES:
                    exceeded = True
                    logger.warning(
                        "工具 %s 连续失败 %d 次，终止本轮重试: user=%d, resume=%d",
                        tc.name,
                        tool_retries[tc.name],
                        user_id,
                        resume_id,
                    )
            if exceeded:
                break
        else:
            # 有工具成功 → 成功工具计数清零（失败工具保留计数继续累计）
            for tc, (_result, is_error, _sources, _usage) in zip(response.tool_calls, results):
                if not is_error:
                    tool_retries[tc.name] = 0

        # D2: 更新最近失败分类（本轮有失败时；成功轮不覆盖，保留最近一次失败信号）。
        # 反思侧信道（answer_from_index 内部 agentic RAG 反思判定的 fault_type）优先。
        if any(is_error for _r, is_error, _s, _u in results):
            recent_fault_type = _classify_recent_fault(
                user_id, question, response.tool_calls, results
            )

        # M3 增强：ToolLoopDetector 替代旧方案的签名重复检测
        # 记录本轮所有工具调用到滑动窗口 → 检测循环模式 → 按级别响应
        for tc, (tool_result, is_error, _sources, _usage) in zip(
            response.tool_calls, results
        ):
            try:
                tc_args = json.loads(tc.arguments) if tc.arguments else {}
            except json.JSONDecodeError:
                tc_args = {}
            rec = loop_detector.record(tc.name, tc_args, tc.id)
            # 回填执行结果到记录（供后续审计）
            loop_detector.update_outcome(
                rec,
                outcome_kind="error" if is_error else "success",
                result_hash=hashlib.md5(tool_result[:500].encode()).hexdigest()[:8],
            )
        loop_result = loop_detector.detect_loop()
        if loop_result["stuck"]:
            stuck = True
            stuck_level = loop_result["level"]
            logger.warning(
                "ReAct 工具循环检测（level=%s）: %s user=%d resume=%d rounds=%d",
                stuck_level,
                loop_result["reason"],
                user_id,
                resume_id,
                rounds,
            )
            if stuck_level == "critical":
                # critical 级别：注入更强终止提示，下一轮开头 break
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "严重循环检测：你已连续多次执行相同操作且未产生有效进展。"
                            "请立即停止所有工具调用，基于已有信息直接给出最终回答。"
                        ),
                    }
                )

    # 6. 强制收敛：无工具调用，用 CHAT_MODEL（流式：推理过程实时推给前端）
    messages = manage_l1_context(messages)
    response = await _stream_final_round(
        messages=messages,
        user_id=user_id,
        emit=_emit,
    )

    _accumulate_usage(total_usage, response)
    await _emit_llm_events(response)

    await _emit({"type": "agent_done", "content": response.content})
    _log_agent_timing("force")
    if checkpoint_key:
        await _clear_react_checkpoint(checkpoint_key)
    return ReactLoopResult(
        answer=response.content,
        process_trace=process_trace,
        usage=total_usage,
        sources=_deduplicate_sources(all_sources),
        db_trace=_build_db_trace(system_prompt, db_rounds, FINAL_MODEL),
        checkpoint_restored=restored_from_checkpoint,
    )


# ── 辅助函数 ──────────────────────────────────────────────────


def _tool_round_signature(tool_calls: list) -> tuple[str, ...]:
    """本轮 tool_call 的签名（工具名 + 参数原文），用于 M3 is_stuck 重复检测。

    完全相同工具 + 完全相同参数 → 相同签名；参数变化（如换搜索词）→ 签名不同。
    """
    return tuple(sorted(f"{tc.name}:{tc.arguments}" for tc in (tool_calls or [])))


def _accumulate_usage(total: dict, response) -> None:
    """累加 LLM usage 到总计。response 可为 LLMToolResponse 或 dict。"""
    usage = response.usage if hasattr(response, "usage") else response
    total["prompt_tokens"] += usage.get("prompt_tokens", 0)
    total["completion_tokens"] += usage.get("completion_tokens", 0)


async def _stream_middle_round(
    messages: list[dict],
    tools: list[dict] | None,
    user_id: int,
    model: str,
    emit: Callable[[dict], Awaitable[None]],
) -> LLMToolResponse:
    """中间轮流式调用：reasoning 逐段实时 emit agent_thought，聚合返回 LLMToolResponse。

    作用：
    - 用 llm_generate_with_tools_stream 代替非流式调用，每段 reasoning_content
      边生成边通过 emit 推成 agent_thought 事件（前端追加到当前"思考"step）。
    - token（中间轮过渡文案）聚合但不推送，避免干扰最终答案。
    - usage 由调用方在返回后统一 emit（保持每轮一次语义，Spec A#28）。

    返回聚合后的 LLMToolResponse，继续走 ReAct 循环（坏 tool_call 回灌等不变）。
    """
    content_parts: list[str] = []
    reasoning_parts: list[str] = []
    tool_calls: list[ToolCall] = []
    round_usage: dict = {"prompt_tokens": 0, "completion_tokens": 0}
    _llm_t0 = time.perf_counter()
    _first_chunk = True

    async def _consume() -> None:
        """消费流式事件（DeepInterview _guarded 对照：整个流包一层墙钟超时）。"""
        nonlocal round_usage, tool_calls, _first_chunk
        async for ev in llm_generate_with_tools_stream(
            messages=messages,
            tools=tools,
            user_id=user_id,
            model=model,
        ):
            if _first_chunk:
                _first_chunk = False
                logger.info(
                    "middle_round_first_chunk_ms=%d",
                    round((time.perf_counter() - _llm_t0) * 1000),
                )
            et = ev.get("type")
            if et == "reasoning":
                reasoning_parts.append(ev["content"])
                await emit({"type": "agent_thought", "content": ev["content"]})
            elif et == "token":
                content_parts.append(ev["content"])
            elif et == "usage":
                round_usage = {
                    "prompt_tokens": ev.get("prompt_tokens", 0),
                    "completion_tokens": ev.get("completion_tokens", 0),
                }
            elif et == "done":
                tool_calls = ev["tool_calls"]

    try:
        await asyncio.wait_for(_consume(), timeout=settings.REACT_LLM_TIMEOUT)
    except asyncio.TimeoutError:
        # 超时护栏（DeepInterview _guarded 对照）：降级为提示而非永久挂起
        logger.warning("middle round LLM 超时（%ss），降级为提示", settings.REACT_LLM_TIMEOUT)
        return LLMToolResponse(
            content="生成超时，请重试。",
            tool_calls=[],
            reasoning_content="".join(reasoning_parts) or None,
            usage=round_usage,
        )

    return LLMToolResponse(
        content="".join(content_parts),
        tool_calls=tool_calls,
        reasoning_content="".join(reasoning_parts) or None,
        usage=round_usage,
    )


async def _stream_final_round(
    messages: list[dict],
    user_id: int,
    emit: Callable[[dict], Awaitable[None]],
) -> LLMToolResponse:
    """最终轮流式调用：reasoning 逐段实时 emit agent_thought。

    与中间轮的区别：
    - 不传 tools（最终轮强制无工具回答）
    - content（答案）也流式接收，聚合后由 agent_done 推送
    - reasoning_content 逐段 emit 为 agent_thought（实时展示思考过程）
    """
    content_parts: list[str] = []
    reasoning_parts: list[str] = []
    round_usage: dict = {"prompt_tokens": 0, "completion_tokens": 0}
    _llm_t0 = time.perf_counter()
    _first_chunk = True

    # 答案实时推送分块参数：LLM 单 token 快但整段答案生成需数秒，
    # 若一次性等 agent_done 才推送，前端"最后一步组织回答"长时间无内容显示。
    # 按字符 / 时间双阈值分块 emit answer_token，前端打字机效果且事件数可控。
    _ANSWER_CHUNK_CHARS = 48
    _ANSWER_CHUNK_INTERVAL = 0.06

    async def _consume() -> None:
        """消费流式事件（DeepInterview _guarded 对照：整个流包一层墙钟超时）。"""
        nonlocal round_usage, _first_chunk
        answer_chunk: list[str] = []
        answer_chunk_len = 0
        _last_emit_t = time.perf_counter()

        async for ev in llm_generate_with_tools_stream(
            messages=messages,
            tools=None,
            user_id=user_id,
            model=FINAL_MODEL,
        ):
            if _first_chunk:
                _first_chunk = False
                logger.info(
                    "final_round_first_chunk_ms=%d",
                    round((time.perf_counter() - _llm_t0) * 1000),
                )
            et = ev.get("type")
            if et == "reasoning":
                reasoning_parts.append(ev["content"])
                await emit({"type": "agent_thought", "content": ev["content"]})
            elif et == "token":
                content_parts.append(ev["content"])
                # 答案分块实时推送（打字机效果），避免最后一步长时间无内容
                answer_chunk.append(ev["content"])
                answer_chunk_len += len(ev["content"])
                _now = time.perf_counter()
                if (
                    answer_chunk_len >= _ANSWER_CHUNK_CHARS
                    or _now - _last_emit_t >= _ANSWER_CHUNK_INTERVAL
                ):
                    await emit({"type": "answer_token", "content": "".join(answer_chunk)})
                    answer_chunk = []
                    answer_chunk_len = 0
                    _last_emit_t = _now
            elif et == "usage":
                round_usage = {
                    "prompt_tokens": ev.get("prompt_tokens", 0),
                    "completion_tokens": ev.get("completion_tokens", 0),
                }

        # 流结束：flush 剩余的答案分块
        if answer_chunk_len:
            await emit({"type": "answer_token", "content": "".join(answer_chunk)})

    try:
        await asyncio.wait_for(_consume(), timeout=settings.REACT_LLM_TIMEOUT)
    except asyncio.TimeoutError:
        # 超时护栏（DeepInterview _guarded 对照）：降级为提示而非永久挂起
        logger.warning("final round LLM 超时（%ss），降级为提示", settings.REACT_LLM_TIMEOUT)
        return LLMToolResponse(
            content="生成超时，请重试。",
            tool_calls=[],
            reasoning_content="".join(reasoning_parts) or None,
            usage=round_usage,
        )

    return LLMToolResponse(
        content="".join(content_parts),
        tool_calls=[],
        reasoning_content="".join(reasoning_parts) or None,
        usage=round_usage,
    )


def _build_assistant_message(response: LLMToolResponse) -> dict:
    """构造 assistant 消息（含 tool_calls，OpenAI 格式）。

    thinking/reasoning 模型（如 deepseek-v4-flash）在 tool 轮会返回 reasoning_content，
    多轮请求必须把该字段原样回传，否则 DeepSeek 报 400
    "reasoning_content in the thinking mode must be passed back to the API"。
    """
    msg = {
        "role": "assistant",
        "content": response.content or "",
        "tool_calls": [
            {
                "id": tc.id,
                "type": "function",
                "function": {"name": tc.name, "arguments": tc.arguments},
            }
            for tc in response.tool_calls
        ],
    }
    if response.reasoning_content:
        msg["reasoning_content"] = response.reasoning_content
    return msg


async def _execute_tool_call(
    tc: ToolCall,
    db: AsyncSession,
    user_id: int,
    emit=None,
    *,
    approval_lock: asyncio.Lock | None = None,
    round_no: int | None = None,
) -> tuple[str, bool, list[dict], dict]:
    """执行单个 tool_call。

    三层防御：
    1. 参数 JSON 解析
    2. 工具名查找
    3. 工具执行（含 pydantic 校验 + 注入检测 + 归属校验）

    D1 审批门：命中 requires_approval 的工具经 _handle_tool_approval 挂起等用户决议。
    无事件通道（emit=None，如测试/无前端）时审批门退化为直接执行，保持旧行为。

    emit：事件回调，注入工具以支持工具内部 LLM 流式 token 推送（tool_stream 事件）。
    approval_lock：本轮审批串行化锁（同一轮并行工具的审批请求逐个处理，前端一次只弹一个）。
    round_no：当前 ReAct 轮次（写入 approval_request 事件供前端展示）。

    Returns:
        (result_text, is_error, sources, usage) — sources 为工具结构化来源，usage 为工具内部 LLM token 消耗
    """
    # 1. 解析参数 JSON
    try:
        args = json.loads(tc.arguments) if tc.arguments else {}
    except json.JSONDecodeError:
        return (
            f"参数 JSON 解析失败: {tc.arguments}",
            True,
            [],
            {"prompt_tokens": 0, "completion_tokens": 0},
        )

    # 2. 查找工具（A3: 未知工具附可用列表，模型几乎必然自愈——借鉴 pydantic-ai _resolve_tool）
    tool_class = get_tool_by_name(tc.name)
    if tool_class is None:
        available = ", ".join(sorted(t.name for t in get_tools_for_agent()))
        return (
            f"工具 '{tc.name}' 不存在。可用工具: {available}。请从列表中选择正确的工具。",
            True,
            [],
            {"prompt_tokens": 0, "completion_tokens": 0},
        )

    # 3. 实例化并执行（注入 emit 供工具内部 LLM 流式推送）
    tool = tool_class(db=db, user_id=user_id, emit=emit)
    # D1（P0-4）: 无事件通道（测试/无前端）且审批模式为 "sse" 时无用户可确认，
    # 审批门退化为直接执行（保持旧行为）。mode="always" 时 emit=None 也拦截审批。
    if (
        emit is None
        and tool.is_approval_required()
        and getattr(settings, "TOOL_APPROVAL_MODE", "sse") == "sse"
    ):
        tool.mark_approval_granted()
    # 审批增强：用户曾"始终允许"该工具 → 自动放行，跳过审批门（免重复弹窗）。
    # best-effort：Redis 不可用返回 False，退化为正常审批。
    if (
        tool.is_approval_required()
        and not getattr(tool, "_approval_granted", False)
        and await check_tool_approval(user_id, tc.name)
    ):
        tool.mark_approval_granted()
    _tool_t0 = time.perf_counter()
    _timeout = _tool_exec_timeout(tc.name)
    try:
        # 工具执行墙钟超时护栏（外部 API 挂起不卡死）：超时返回降级提示并计入坏调用，
        # 由 A3 per-tool 重试预算控制连续超时上限（避免反复重试同一挂起工具烧 token）。
        result = await asyncio.wait_for(
            tool.execute(**args), timeout=_timeout
        )
        # D1: 命中审批拦截钩子 → 走审批门（发射 approval_request → 挂起等决议）
        if isinstance(result, ApprovalRequired):
            approval_start = time.perf_counter()
            outcome = await _handle_tool_approval(
                tc,
                tool,
                result,
                user_id,
                round_no=round_no,
                emit=emit,
                approval_lock=approval_lock,
            )
            logger.info(
                "tool_exec: %s 实际执行=%.0fms 审批等待=%.0fms",
                tc.name,
                (approval_start - _tool_t0) * 1000,
                (time.perf_counter() - approval_start) * 1000,
            )
            return outcome
        logger.info(
            "tool_exec: %s %.0fms", tc.name, (time.perf_counter() - _tool_t0) * 1000
        )
        return (
            result,
            False,
            getattr(tool, "sources", []),
            getattr(tool, "last_usage", {"prompt_tokens": 0, "completion_tokens": 0}),
        )
    except asyncio.TimeoutError:
        logger.warning(
            "工具执行超时（%ss）: %s user=%d", _timeout, tc.name, user_id
        )
        return (
            f"⛔ 工具 {tc.name} 执行超时（超过 {_timeout}s），请稍后重试或换一种方式。",
            True,  # 超时算坏调用 → A3 累计重试预算，连续超限终止本轮
            [],
            {"prompt_tokens": 0, "completion_tokens": 0},
        )
    except ToolRetryError as e:
        # A3 契约化：可重试错误（参数格式等）→ 结构化错误文本回灌，累计坏调用
        logger.warning("工具可重试失败: %s, args=%s, error=%s", tc.name, tc.arguments, e)
        logger.info("tool_exec: %s %.0fms (retry)", tc.name, (time.perf_counter() - _tool_t0) * 1000)
        return f"[参数或状态错误] {e}", True, [], {"prompt_tokens": 0, "completion_tokens": 0}
    except ToolFailed as e:
        # A3 契约化：终端失败（业务确定性失败）→ 不累计坏调用，LLM 应换路径
        logger.info("工具终端失败（不重试）: %s, error=%s", tc.name, e)
        logger.info("tool_exec: %s %.0fms (failed)", tc.name, (time.perf_counter() - _tool_t0) * 1000)
        return f"⛔ {e}", False, [], {"prompt_tokens": 0, "completion_tokens": 0}
    except Exception as e:
        logger.warning("工具执行失败: %s, args=%s, error=%s", tc.name, tc.arguments, e)
        logger.info("tool_exec: %s %.0fms (error)", tc.name, (time.perf_counter() - _tool_t0) * 1000)
        return f"工具执行失败: {e}", True, [], {"prompt_tokens": 0, "completion_tokens": 0}


async def _handle_tool_approval(
    tc: ToolCall,
    tool: Tool,
    approval: ApprovalRequired,
    user_id: int,
    *,
    round_no: int | None = None,
    emit=None,
    approval_lock: asyncio.Lock | None = None,
) -> tuple[str, bool, list[dict], dict]:
    """D1 审批门：发射 approval_request → 挂起等用户决议 → 按决议执行/拒绝。

    - approved → 放行重执行工具（mark_approval_granted 后 execute 跳过拦截钩子）
    - denied   → 以 outcome='denied' 的 tool result 回灌 LLM（提示换方案），
                 返回 is_error=False，**不累计坏调用**（区别于 ToolRetryError/ToolFailed）

    approval_lock 串行化同一轮并行工具的审批请求，保证前端一次只弹一个弹窗。
    """
    # 显式 acquire/release（审批可能挂起数分钟，用 try/finally 确保锁最终释放）
    if approval_lock is not None:
        await approval_lock.acquire()
    try:
        approval_id = uuid4().hex
        register_approval(approval_id, user_id)
        try:
            if emit is not None:
                await emit(
                    {
                        "type": "approval_request",
                        "approval_id": approval_id,
                        "tool_name": approval.tool_name,
                        "args": json.dumps(approval.arguments, ensure_ascii=False),
                        "summary": approval.summary,
                        "round": round_no,
                        # 审批增强（借鉴 OpenClaw severity）：info/warning/critical，
                        # 前端据此区分弹窗样式；critical 触发审计日志。
                        "severity": getattr(approval, "severity", "warning"),
                    }
                )
                decision = await wait_for_approval(approval_id)
                # allow-always：用户选择"始终允许该工具"→ 记入偏好，后续同工具自动放行
                if decision == "allow_always":
                    await remember_tool_approval(user_id, approval.tool_name)
                    decision = "approved"
                await emit(
                    {
                        "type": "approval_decision",
                        "approval_id": approval_id,
                        "tool_name": approval.tool_name,
                        "decision": decision,
                    }
                )
            else:
                # 无事件通道（不应到达：_execute_tool_call 已对 emit=None 放行）
                decision = "approved"

            # critical 审计日志（审批增强）：高风险工具放行/拒绝均留痕
            if getattr(approval, "severity", "warning") == "critical":
                logger.info(
                    "CRITICAL 审批记录: tool=%s decision=%s user=%d approval_id=%s round=%s",
                    approval.tool_name, decision, user_id, approval_id, round_no,
                )

            if decision == "approved":
                tool.mark_approval_granted()
                _approval_timeout = _tool_exec_timeout(approval.tool_name)
                try:
                    result = await asyncio.wait_for(
                        tool.execute(**approval.arguments),
                        timeout=_approval_timeout,
                    )
                except asyncio.TimeoutError:
                    logger.warning(
                        "审批通过后工具执行超时（%ss）: %s",
                        _approval_timeout,
                        approval.tool_name,
                    )
                    return (
                        f"⛔ 工具 {approval.tool_name} 执行超时（超过 {_approval_timeout}s），请稍后重试。",
                        True,
                        [],
                        {"prompt_tokens": 0, "completion_tokens": 0},
                    )
                return (
                    result,
                    False,
                    getattr(tool, "sources", []),
                    getattr(tool, "last_usage", {"prompt_tokens": 0, "completion_tokens": 0}),
                )

            logger.info(
                "工具被用户拒绝: %s approval_id=%s user=%d round=%s",
                approval.tool_name,
                approval_id,
                user_id,
                round_no,
            )
            return (
                "用户拒绝执行该工具，请换一种方案，或直接基于已有信息回答用户。",
                False,  # 用户拒绝 ≠ 工具失败：不累计坏调用，LLM 应换路径
                [],
                {"prompt_tokens": 0, "completion_tokens": 0},
            )
        finally:
            drop_approval(approval_id)  # wait_for_approval 已清理；此处兜底
    finally:
        if approval_lock is not None:
            approval_lock.release()


def _classify_recent_fault(
    user_id: int,
    question: str,
    tool_calls: list,
    results: list[tuple],
) -> str:
    """D2: 分类最近一次失败类型（tau-bench fault_type）。

    优先级：
    1. 反思侧信道——answer_from_index 工具内部 agentic RAG 反思判定的 fault_type
    2. 本轮工具错误文本——参数错误 → used_wrong_tool_argument；
       未知工具 → used_wrong_tool；其余 → goal_partially_completed
    """
    try:
        from services.agentic_rag.reflection import get_fault_type

        reflected = get_fault_type(user_id, question)
        if reflected:
            return reflected
    except Exception:
        logger.debug("读取反思 fault_type 侧信道失败（忽略）", exc_info=True)

    has_arg_error = False
    has_wrong_tool = False
    for tc, (tool_result, is_error, _sources, _usage) in zip(tool_calls, results):
        if not is_error:
            continue
        if tool_result.startswith("[参数或状态错误]"):
            has_arg_error = True
        elif "不存在" in tool_result and "可用工具" in tool_result:
            has_wrong_tool = True
    if has_wrong_tool:
        return "used_wrong_tool"
    if has_arg_error:
        return "used_wrong_tool_argument"
    return "goal_partially_completed"


async def _execute_tool_call_with_limit(
    tc: ToolCall,
    user_id: int,
    semaphore: asyncio.Semaphore,
    emit=None,
    *,
    approval_lock: asyncio.Lock | None = None,
    round_no: int | None = None,
) -> tuple[str, bool, list[dict], dict]:
    """带 Semaphore 限流的工具执行（Spec A#32：限单轮工具并发）。

    P0-4 修复：并行工具不再共享请求 session —— 每个工具用独立 AsyncSessionLocal，
    避免同一 aiomysql 连接被多个 coroutine 并发 execute
    （readexactly() called while another coroutine is already waiting / Command Out of Sync）。
    """
    async with semaphore:
        # 每工具独立 session，用完即关；避免共享请求 session 的并发读冲突
        async with AsyncSessionLocal() as tool_db:
            return await _execute_tool_call(
                tc,
                tool_db,
                user_id,
                emit,
                approval_lock=approval_lock,
                round_no=round_no,
            )


def _deduplicate_sources(sources: list[dict]) -> list[dict]:
    """按 text 字段去重来源（Spec A#10: 多轮多 search 引用来源去重）。"""
    seen: set[str] = set()
    deduped: list[dict] = []
    for s in sources:
        text = s.get("text", "")
        if text not in seen:
            seen.add(text)
            deduped.append(s)
    return deduped


def _build_db_trace(
    system_prompt: str,
    db_rounds: list[dict],
    final_model: str | None = None,
) -> dict:
    """构建 DB 持久化的完整 prompt trace（Spec 行 459）。

    DB 存完整 prompt（system + 记忆注入 + 工具序列 + 模型），
    SSE done 事件只发紧凑摘要（轮数/工具序列/耗时）。
    """
    return {
        "system_prompt": system_prompt,
        "rounds": db_rounds,
        "total_rounds": len(db_rounds),
        "final_model": final_model,
    }
