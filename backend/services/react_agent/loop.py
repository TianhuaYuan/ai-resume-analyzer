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
import time
from dataclasses import dataclass, field
from typing import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.database import AsyncSessionLocal
from services.rag.pipeline import (
    LLMToolResponse,
    ToolCall,
    llm_generate_with_tools,
    llm_generate_with_tools_stream,
)
from services.react_agent.memory import assemble_system_prompt, manage_l1_context
from services.react_agent.tools import (
    get_agent_schemas,
    get_tool_by_name,
    get_tools_for_agent,
)
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
        """写入 process_trace 并调用事件回调（供 streaming 层使用）。

        tool_stream 为逐 token 高频事件，只透传前端、不入 process_trace，
        避免撑爆事件日志与 agent_done 的紧凑 trace。
        """
        if event.get("type") != "tool_stream":
            process_trace.append(event)
        if event_callback:
            await event_callback(event)

    async def _emit_llm_events(resp: LLMToolResponse) -> None:
        """LLM 调用后推 usage 事件（Spec A#28）。

        reasoning_content 已在流式调用中逐段 emit 为 agent_thought，此处只推 usage。
        """
        await _emit({
            "type": "usage",
            "usage": dict(resp.usage),
            "total": dict(total_usage),
        })

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
    system_prompt = await assemble_system_prompt(
        db, user_id, resume_id, builder=(tool_mode == "builder"), query=question,
    )
    _phases["prompt_assembly_ms"] = round((time.perf_counter() - _t0) * 1000)

    # 3. 初始化消息
    messages: list[dict] = [
        {"role": "system", "content": system_prompt},
    ]
    if history:
        messages.extend(history)
    messages.append({"role": "user", "content": question})

    # 4. 获取工具 schemas（v2: 统一使用 unified 工具集 + 相关性过滤）
    from services.react_agent.tool_gate import filter_agent_tools

    agent_tools = filter_agent_tools(question, get_tools_for_agent())
    tool_schemas = [tc().to_openai_schema() for tc in agent_tools]

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
                tc, user_id, tool_semaphore, emit=_emit
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
            return ReactLoopResult(
                answer=result,
                process_trace=process_trace,
                usage=total_usage,
                sources=_deduplicate_sources(sources),
                db_trace=_build_db_trace(system_prompt, [], FINAL_MODEL),
            )

    # 5. ReAct 循环
    bad_call_count = 0
    rounds = 0
    _llm_round_ms = 0.0
    _tool_exec_ms = 0.0

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

        # 无 tool_call → 直接回答
        if not response.tool_calls:
            await _emit({"type": "agent_done", "content": response.content})
            _log_agent_timing("done")
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
        _tool_start = time.perf_counter()
        results = await asyncio.gather(*[
            _execute_tool_call_with_limit(tc, user_id, tool_semaphore, emit=_emit)
            for tc in response.tool_calls
        ])
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
        for tc, (tool_result, is_error, tool_sources, tool_usage) in zip(response.tool_calls, results):
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

            # 累计工具内部 LLM 调用的 token 消耗到主 usage（builder 工具内部有独立 LLM 调用）
            _accumulate_usage(total_usage, tool_usage)

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

        # 工具执行完毕后推送累计 usage（含工具内部 LLM 消耗），让前端实时更新 token 计数
        await _emit({"type": "usage", "usage": dict(total_usage), "total": dict(total_usage)})

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
    return ReactLoopResult(
        answer=response.content,
        process_trace=process_trace,
        usage=total_usage,
        sources=_deduplicate_sources(all_sources),
        db_trace=_build_db_trace(system_prompt, db_rounds, FINAL_MODEL),
    )


# ── 辅助函数 ──────────────────────────────────────────────────


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
        elif et == "usage":
            round_usage = {
                "prompt_tokens": ev.get("prompt_tokens", 0),
                "completion_tokens": ev.get("completion_tokens", 0),
            }

    return LLMToolResponse(
        content="".join(content_parts),
        tool_calls=[],
        reasoning_content="".join(reasoning_parts) or None,
        usage=round_usage,
    )


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
    emit=None,
) -> tuple[str, bool, list[dict], dict]:
    """执行单个 tool_call。

    三层防御：
    1. 参数 JSON 解析
    2. 工具名查找
    3. 工具执行（含 pydantic 校验 + 注入检测 + 归属校验）

    emit：事件回调，注入工具以支持工具内部 LLM 流式 token 推送（tool_stream 事件）。

    Returns:
        (result_text, is_error, sources, usage) — sources 为工具结构化来源，usage 为工具内部 LLM token 消耗
    """
    # 1. 解析参数 JSON
    try:
        args = json.loads(tc.arguments) if tc.arguments else {}
    except json.JSONDecodeError:
        return f"参数 JSON 解析失败: {tc.arguments}", True, [], {"prompt_tokens": 0, "completion_tokens": 0}

    # 2. 查找工具
    tool_class = get_tool_by_name(tc.name)
    if tool_class is None:
        return f"工具 '{tc.name}' 不存在", True, [], {"prompt_tokens": 0, "completion_tokens": 0}

    # 3. 实例化并执行（注入 emit 供工具内部 LLM 流式推送）
    tool = tool_class(db=db, user_id=user_id, emit=emit)
    try:
        result = await tool.execute(**args)
        return result, False, getattr(tool, "sources", []), getattr(tool, "last_usage", {"prompt_tokens": 0, "completion_tokens": 0})
    except Exception as e:
        logger.warning("工具执行失败: %s, args=%s, error=%s", tc.name, tc.arguments, e)
        return f"工具执行失败: {e}", True, [], {"prompt_tokens": 0, "completion_tokens": 0}


async def _execute_tool_call_with_limit(
    tc: ToolCall,
    user_id: int,
    semaphore: asyncio.Semaphore,
    emit=None,
) -> tuple[str, bool, list[dict], dict]:
    """带 Semaphore 限流的工具执行（Spec A#32：限单轮工具并发）。

    P0-4 修复：并行工具不再共享请求 session —— 每个工具用独立 AsyncSessionLocal，
    避免同一 aiomysql 连接被多个 coroutine 并发 execute
    （readexactly() called while another coroutine is already waiting / Command Out of Sync）。
    """
    async with semaphore:
        # 每工具独立 session，用完即关；避免共享请求 session 的并发读冲突
        async with AsyncSessionLocal() as tool_db:
            return await _execute_tool_call(tc, tool_db, user_id, emit)


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
