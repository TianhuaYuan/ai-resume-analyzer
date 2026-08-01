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
import json
import logging
from dataclasses import dataclass, field
from typing import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.database import AsyncSessionLocal
from services.rag.pipeline import LLMToolResponse, ToolCall, llm_generate_with_tools
from services.react_agent.memory import assemble_system_prompt, manage_l1_context
from services.react_agent.tools import get_agent_schemas, get_builder_schemas, get_tool_by_name
from services.token_quota import check_quota

logger = logging.getLogger(__name__)

# ── 常量 ──────────────────────────────────────────────────────
MAX_ROUNDS = settings.REACT_MAX_TOOL_ROUNDS  # Spec A#6: 6 轮工具上限（config 可调）
MAX_BAD_TOOL_RETRIES = 2
AGENT_CONCURRENCY_LIMIT = 5

# 中间轮用 JUDGE_MODEL（flash 快），最终轮用 CHAT_MODEL
MIDDLE_MODEL = "judge"
FINAL_MODEL = None  # None → 默认 CHAT_MODEL


@dataclass
class ReactLoopResult:
    """ReAct 循环返回值。"""

    answer: str
    process_trace: list[dict] = field(default_factory=list)
    usage: dict = field(default_factory=lambda: {"prompt_tokens": 0, "completion_tokens": 0})
    sources: list[dict] = field(default_factory=list)  # Spec A#10: search_resume 来源去重
    db_trace: dict = field(default_factory=dict)  # Spec 行 459: 完整 prompt 进 DB


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
        """写入 process_trace 并调用事件回调（供 streaming 层使用）。"""
        process_trace.append(event)
        if event_callback:
            await event_callback(event)

    async def _emit_llm_events(resp: LLMToolResponse) -> None:
        """LLM 调用后推 agent_thought + usage 事件（Spec A#7/A#28）。"""
        if resp.reasoning_content:
            await _emit({"type": "agent_thought", "content": resp.reasoning_content})
        await _emit({
            "type": "usage",
            "usage": dict(resp.usage),
            "total": dict(total_usage),
        })

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

    # 2. 装配 system prompt（L2 历史 + L3 画像注入；builder 模式用允许生成的专属指令）
    system_prompt = await assemble_system_prompt(
        db, user_id, resume_id, builder=(tool_mode == "builder"),
    )

    # 3. 初始化消息
    messages: list[dict] = [
        {"role": "system", "content": system_prompt},
    ]
    if history:
        messages.extend(history)
    messages.append({"role": "user", "content": question})

    # 4. 获取工具 schemas（builder 模式用 builder 工具）
    tool_schemas = get_builder_schemas() if tool_mode == "builder" else get_agent_schemas()

    # 5. ReAct 循环
    bad_call_count = 0
    rounds = 0

    while rounds < MAX_ROUNDS:
        rounds += 1

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
                )

        # L1 上下文管理（逐出旧轮次，截断工具结果）
        messages = manage_l1_context(messages)

        # 调用 LLM（中间轮用 JUDGE_MODEL = flash 快）
        response = await llm_generate_with_tools(
            messages=messages,
            tools=tool_schemas,
            user_id=user_id,
            model=MIDDLE_MODEL,
        )

        _accumulate_usage(total_usage, response)
        await _emit_llm_events(response)

        # 无 tool_call → 直接回答
        if not response.tool_calls:
            await _emit({"type": "agent_done", "content": response.content})
            return ReactLoopResult(
                answer=response.content,
                process_trace=process_trace,
                usage=total_usage,
                sources=_deduplicate_sources(all_sources),
                db_trace=_build_db_trace(system_prompt, db_rounds, FINAL_MODEL),
            )

        # 有 tool_call → 并行执行工具（Spec A#21: asyncio.gather）
        messages.append(_build_assistant_message(response))

        # 先发所有 tool_call 事件（让用户立刻看到 Agent 在调哪些工具）
        for tc in response.tool_calls:
            await _emit({
                "type": "tool_call",
                "name": tc.name,
                "arguments": tc.arguments,
                "id": tc.id,
            })

        # 并行执行所有工具（Spec A#32: Semaphore 限单轮并发）
        tool_semaphore = _get_tool_semaphore()
        results = await asyncio.gather(*[
            _execute_tool_call_with_limit(tc, user_id, tool_semaphore)
            for tc in response.tool_calls
        ])

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

        # 处理结果：发 tool_result/tool_error 事件 + 回灌 messages + 收集 sources
        all_bad = True
        for tc, (tool_result, is_error, tool_sources) in zip(response.tool_calls, results):
            if is_error:
                await _emit({
                    "type": "tool_error",
                    "name": tc.name,
                    "error": tool_result,
                    "id": tc.id,
                })
            else:
                await _emit({
                    "type": "tool_result",
                    "name": tc.name,
                    "result": tool_result,
                    "id": tc.id,
                })
                all_bad = False

            # 收集工具来源（Spec A#10: search_resume 来源聚合）
            all_sources.extend(tool_sources)

            # tool 结果/错误回灌到 messages
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": tool_result,
            })

            # 记录工具结果到 db_round（截断避免 DB 膨胀）
            db_round["tool_results"].append({
                "name": tc.name,
                "result": tool_result[:500],
                "is_error": is_error,
            })

        # 坏调用计数与强制收敛
        if all_bad:
            bad_call_count += 1
            if bad_call_count >= MAX_BAD_TOOL_RETRIES:
                logger.warning(
                    "连续 %d 次坏 tool_call，强制收敛: user=%d, resume=%d",
                    bad_call_count, user_id, resume_id,
                )
                break
        else:
            bad_call_count = 0

    # 6. 强制收敛：无工具调用，用 CHAT_MODEL
    messages = manage_l1_context(messages)
    response = await llm_generate_with_tools(
        messages=messages,
        tools=None,
        user_id=user_id,
        model=FINAL_MODEL,
    )

    _accumulate_usage(total_usage, response)
    await _emit_llm_events(response)

    await _emit({"type": "agent_done", "content": response.content})
    return ReactLoopResult(
        answer=response.content,
        process_trace=process_trace,
        usage=total_usage,
        sources=_deduplicate_sources(all_sources),
        db_trace=_build_db_trace(system_prompt, db_rounds, FINAL_MODEL),
    )


# ── 辅助函数 ──────────────────────────────────────────────────


def _accumulate_usage(total: dict, response: LLMToolResponse) -> None:
    """累加 LLM usage 到总计。"""
    total["prompt_tokens"] += response.usage.get("prompt_tokens", 0)
    total["completion_tokens"] += response.usage.get("completion_tokens", 0)


def _build_assistant_message(response: LLMToolResponse) -> dict:
    """构造 assistant 消息（含 tool_calls，OpenAI 格式）。"""
    return {
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


async def _execute_tool_call(
    tc: ToolCall,
    db: AsyncSession,
    user_id: int,
) -> tuple[str, bool, list[dict]]:
    """执行单个 tool_call。

    三层防御：
    1. 参数 JSON 解析
    2. 工具名查找
    3. 工具执行（含 pydantic 校验 + 注入检测 + 归属校验）

    Returns:
        (result_text, is_error, sources) — sources 为工具结构化来源
    """
    # 1. 解析参数 JSON
    try:
        args = json.loads(tc.arguments) if tc.arguments else {}
    except json.JSONDecodeError:
        return f"参数 JSON 解析失败: {tc.arguments}", True, []

    # 2. 查找工具
    tool_class = get_tool_by_name(tc.name)
    if tool_class is None:
        return f"工具 '{tc.name}' 不存在", True, []

    # 3. 实例化并执行
    tool = tool_class(db=db, user_id=user_id)
    try:
        result = await tool.execute(**args)
        return result, False, getattr(tool, "sources", [])
    except Exception as e:
        logger.warning("工具执行失败: %s, args=%s, error=%s", tc.name, tc.arguments, e)
        return f"工具执行失败: {e}", True, []


async def _execute_tool_call_with_limit(
    tc: ToolCall,
    user_id: int,
    semaphore: asyncio.Semaphore,
) -> tuple[str, bool, list[dict]]:
    """带 Semaphore 限流的工具执行（Spec A#32：限单轮工具并发）。

    P0-4 修复：并行工具不再共享请求 session —— 每个工具用独立 AsyncSessionLocal，
    避免同一 aiomysql 连接被多个 coroutine 并发 execute
    （readexactly() called while another coroutine is already waiting / Command Out of Sync）。
    """
    async with semaphore:
        # 每工具独立 session，用完即关；避免共享请求 session 的并发读冲突
        async with AsyncSessionLocal() as tool_db:
            return await _execute_tool_call(tc, tool_db, user_id)


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
