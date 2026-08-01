"""T17: 流式 SSE + /ask/agent 支持。

react_loop_stream 包装 react_loop，以 async generator 形式产出 SSE 事件：
- agent_start: 流开始
- tool_call / tool_result / tool_error: 工具调用过程
- agent_done: 最终答案（含 qa_id + process_trace + usage）
- quota_exceeded: 配额不足
- error: 内部错误

占位记录策略：
- 流开始时创建 status=streaming 的 QA 记录
- 流结束时更新 answer + status=complete
- 断连时占位记录保留（前端可显示"生成中断"）

process_trace 双载荷：
- SSE 推全量事件（实时）
- DB 存紧凑摘要（仅 type + name，节省空间）
"""

import asyncio
import logging
import time

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.qa_history import QAHistory
from services.react_agent.loop import ReactLoopResult, react_loop
from services.react_agent.tools import get_tools_for_agent, get_tools_for_builder

logger = logging.getLogger(__name__)

_SENTINEL = object()

# 工具结果截断阈值（Spec A#11: summary ≤2000 字符）
_RESULT_SUMMARY_MAX = 2000


def _get_tool_list(tool_mode: str) -> list[dict]:
    """获取工具列表（name + description），用于 agent_start 事件。"""
    tool_classes = get_tools_for_builder() if tool_mode == "builder" else get_tools_for_agent()
    return [{"name": tc.name, "description": tc.description} for tc in tool_classes]


def _transform_event(event: dict) -> dict:
    """将 loop 内部事件字段映射为 SSE 协议字段（Spec SSE 事件协议）。

    loop.py 内部用 {name, arguments, result}，
    SSE 协议要求 {tool_name, args, summary, detail}。
    """
    etype = event.get("type")

    if etype == "tool_call":
        return {
            "type": "tool_call",
            "id": event.get("id"),
            "tool_name": event.get("name"),
            "args": event.get("arguments"),
        }

    if etype == "tool_result":
        result_text = event.get("result", "")
        return {
            "type": "tool_result",
            "id": event.get("id"),
            "tool_name": event.get("name"),
            "summary": result_text[:_RESULT_SUMMARY_MAX],
            "detail": result_text,
        }

    if etype == "tool_error":
        return {
            "type": "tool_error",
            "id": event.get("id"),
            "tool_name": event.get("name"),
            "error": event.get("error"),
        }

    if etype == "usage":
        usage = event.get("usage", {})
        return {
            "type": "usage",
            "prompt_tokens": usage.get("prompt_tokens", 0),
            "completion_tokens": usage.get("completion_tokens", 0),
            "total": event.get("total", usage),
        }

    # agent_thought / memory_loaded / quota_exceeded 等无需变换
    return event


def _has_tool_error(trace: list[dict]) -> bool:
    """检查 process_trace 中是否含 tool_error 事件（用于 degraded 判定）。"""
    return any(e.get("type") == "tool_error" for e in trace)


async def save_qa_placeholder(
    db: AsyncSession,
    user_id: int,
    resume_id: int,
    question: str,
    conversation_id: int | None = None,
) -> QAHistory:
    """创建占位 QA 记录，status=streaming。

    流式回答开始时调用，先写入一条空答案记录。
    流结束后由 update_qa_answer 填充最终答案。
    """
    record = QAHistory(
        user_id=user_id,
        resume_id=resume_id,
        question=question,
        answer="",
        sources=[],
        status="streaming",
        token_usage=0,
        conversation_id=conversation_id,
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)
    return record


async def update_qa_answer(
    db: AsyncSession,
    qa_id: int,
    answer: str,
    sources: list[dict],
    token_usage: dict,
    db_trace: dict,
) -> QAHistory | None:
    """更新占位记录的最终答案，status=complete。

    Args:
        db: 数据库会话
        qa_id: 占位记录 ID
        answer: 最终答案文本
        sources: 引用来源列表
        token_usage: {"prompt_tokens": N, "completion_tokens": M}
        db_trace: 完整 prompt trace（system + 记忆注入 + 工具序列 + 模型），
                  存入 DB process_trace 列，供 A12#71 few-shot 导出使用

    Returns:
        更新后的 QAHistory 或 None（记录不存在）
    """
    result = await db.execute(
        select(QAHistory).where(QAHistory.id == qa_id)
    )
    record = result.scalar_one_or_none()
    if record is None:
        logger.warning("占位记录不存在: qa_id=%d", qa_id)
        return None

    record.answer = answer
    record.sources = sources
    record.process_trace = db_trace  # Spec 行 459: 完整 prompt 进 DB
    record.status = "complete"
    record.token_usage = (
        token_usage.get("prompt_tokens", 0)
        + token_usage.get("completion_tokens", 0)
    )

    await db.commit()
    await db.refresh(record)
    return record


async def react_loop_stream(
    db: AsyncSession,
    user_id: int,
    resume_id: int,
    question: str,
    *,
    tool_mode: str = "agent",
    conversation_id: int | None = None,
):
    """流式 ReAct 循环 — async generator 产出 SSE 事件。

    内部通过 asyncio.Queue 桥接 react_loop 的 event_callback 和生成器的 yield：
    1. 启动 react_loop 作为后台 task，事件通过 callback 入队
    2. 等待第一个事件判断配额是否通过
    3. 配额通过 → 创建占位记录 → yield agent_start → 转发事件
    4. 循环结束 → 更新 QA 记录 → yield 富化 agent_done

    事件类型：
    - agent_start: Agent 开始处理
    - tool_call: Agent 决定调用工具（name, arguments, id）
    - tool_result: 工具执行成功（name, result, id）
    - tool_error: 工具执行失败（name, error, id）
    - agent_done: Agent 完成（answer, qa_id, process_trace, usage）
    - quota_exceeded: 配额不足（message）
    - error: 内部错误（message）

    Yields:
        dict: SSE 事件
    """
    queue: asyncio.Queue = asyncio.Queue()
    loop_result: ReactLoopResult | None = None
    loop_error: Exception | None = None
    start_time = time.monotonic()  # Spec: 紧凑摘要含耗时

    async def event_callback(event: dict) -> None:
        """react_loop 事件回调 — 入队供生成器消费。"""
        await queue.put(event)

    async def run_loop() -> None:
        """后台运行 react_loop，结束后放入 SENTINEL 标记完成。"""
        nonlocal loop_result, loop_error
        try:
            loop_result = await react_loop(
                db=db,
                user_id=user_id,
                resume_id=resume_id,
                question=question,
                event_callback=event_callback,
                tool_mode=tool_mode,
            )
        except Exception as e:
            loop_error = e
            logger.error("react_loop 异常: %s", e, exc_info=True)
        finally:
            await queue.put(_SENTINEL)

    task = asyncio.create_task(run_loop())

    try:
        # ── 等待第一个事件 — 判断配额是否通过 ──────────────────
        first_event = await queue.get()

        # 异常情况：loop 在发出任何事件前就结束了
        if first_event is _SENTINEL:
            if loop_error:
                yield {"type": "error", "message": f"Agent 内部错误: {loop_error}"}
            else:
                yield {"type": "error", "message": "Agent 未产出任何事件"}
            return

        # 配额不足 → 不创建占位记录，直接返回
        if first_event.get("type") == "quota_exceeded":
            yield first_event
            await queue.get()  # 消费 SENTINEL
            await task
            return

        # ── 配额通过 → 创建占位记录 ────────────────────────────
        placeholder = await save_qa_placeholder(db, user_id, resume_id, question, conversation_id)
        qa_id = placeholder.id

        # 通知前端 Agent 开始工作（Spec: agent_start 含 resume_id + tools 列表）
        yield {
            "type": "agent_start",
            "resume_id": resume_id,
            "tools": _get_tool_list(tool_mode),
        }

        # 转发第一个事件（agent_done 由末尾统一处理）
        if first_event.get("type") != "agent_done":
            yield _transform_event(first_event)

        # ── 持续转发中间事件（字段映射为 SSE 协议） ──────────
        while True:
            event = await queue.get()
            if event is _SENTINEL:
                break
            # agent_done 从 callback 来的只有 content，
            # 由末尾补充 qa_id + process_trace 后统一 yield
            if event.get("type") == "agent_done":
                continue
            yield _transform_event(event)

        await task

        # ── 检查异常 ──────────────────────────────────────────
        if loop_error:
            yield {"type": "error", "message": f"Agent 执行出错: {loop_error}"}
            return

        if loop_result is None:
            yield {"type": "error", "message": "Agent 未返回结果"}
            return

        # ── 更新 QA 记录（完整 prompt trace 存 DB） ──────────
        sources = getattr(loop_result, "sources", [])  # Spec A#10: search_resume 来源聚合
        await update_qa_answer(
            db=db,
            qa_id=qa_id,
            answer=loop_result.answer,
            sources=sources,
            token_usage=loop_result.usage,
            db_trace=loop_result.db_trace,  # Spec 行 459: 完整 prompt 进 DB
        )

        # ── 产出最终 agent_done 事件（Spec 字段对齐） ────────
        # SSE done.process_trace = 紧凑摘要（轮数/工具序列/耗时），非全量事件列表
        duration_ms = int((time.monotonic() - start_time) * 1000)
        compact_trace = _build_compact_trace(loop_result.process_trace, duration_ms)
        yield {
            "type": "agent_done",
            "answer": loop_result.answer,
            "qa_id": qa_id,
            "sources": sources,
            "token_usage": loop_result.usage,
            "process_trace": compact_trace,
            "degraded": _has_tool_error(loop_result.process_trace),
        }

    except asyncio.CancelledError:
        # 客户端断连 — 取消后台 task，占位记录保留（status=streaming）
        logger.info(
            "Client disconnected from agent stream: user=%d, resume=%d",
            user_id,
            resume_id,
        )
        if not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        raise


def _build_compact_trace(trace: list[dict], duration_ms: int) -> dict:
    """从全量事件列表构建紧凑摘要（Spec 行 482: SSE done.process_trace）。

    SSE done 事件只发紧凑摘要（轮数/工具序列/耗时），
    完整 prompt trace 存 DB（通过 db_trace）。
    """
    tool_sequence: list[str] = []
    rounds = 0
    prev_was_tool_call = False

    for event in trace:
        etype = event.get("type")
        if etype == "tool_call":
            # 连续 tool_call = 同一轮并行调用，只计 1 轮
            if not prev_was_tool_call:
                rounds += 1
            prev_was_tool_call = True
            tool_sequence.append(event.get("name", "unknown"))
        else:
            prev_was_tool_call = False

    return {
        "rounds": rounds,
        "tool_sequence": tool_sequence,
        "duration_ms": duration_ms,
    }
