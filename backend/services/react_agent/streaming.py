"""流式 SSE + /ask/agent 支持。

react_loop_stream 包装 react_loop，以 async generator 形式产出 SSE 事件：
- agent_start: 流开始
- tool_call / tool_result / tool_error: 工具调用过程
- agent_done: 最终答案（含 qa_id + process_trace + token_usage）
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
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from models.qa_history import QAHistory
from services.react_agent.loop import ReactLoopResult, react_loop
from services.react_agent.tools import get_tools_for_agent

logger = logging.getLogger(__name__)

_SENTINEL = object()

# 工具结果截断阈值（ : summary ≤2000 字符）
_RESULT_SUMMARY_MAX = 2000

# 注入上下文的历史轮次上限 / 每条 answer 截断（多轮上下文注入）。
# 修复：react_loop 的 history 参数之前未接线，Agent 每轮都是无上下文的单轮对话
# （L2 摘要仅 200 字截断，方案 A/B 等结论在答案尾部时会丢失）。这里把完整轮次
# 作为 user/assistant 消息注入，由 manage_l1_context 的 L1 预算再兜底逐出。
_HISTORY_ROUNDS = 6
_HISTORY_ANSWER_MAX = 4000


def _get_tool_list(tool_mode: str) -> list[dict]:
    """获取工具列表（name + description），用于 agent_start 事件。

    v2: 统一使用 unified 工具集（qa + builder 合并）。
    """
    tool_classes = get_tools_for_agent()  # unified = qa + builder
    return [{"name": tc.name, "description": tc.description} for tc in tool_classes]


async def _load_conversation_history(
    db: AsyncSession,
    user_id: int,
    resume_id: int,
    conversation_id: int | None,
    limit: int = _HISTORY_ROUNDS,
) -> list[dict]:
    """加载最近 limit 轮完整问答作为对话历史（user/assistant 消息序列）。

    与 L2 摘要（system prompt 里 200 字截断）不同：这里注入完整轮次，
    模型能看到上一轮的完整结论（如"方案 A/B"），解决"回 a 无法识别选择 A"。
    - conversation_id 提供时限定该对话，多对话不串上下文；
    - 只取 status=complete（过滤中断空记录）；
    - answer 截断到 _HISTORY_ANSWER_MAX，剩余由 manage_l1_context 的 L1 预算兜底。
    """
    filters = [
        QAHistory.user_id == user_id,
        QAHistory.resume_id == resume_id,
        QAHistory.status == "complete",
    ]
    if conversation_id is not None:
        filters.append(QAHistory.conversation_id == conversation_id)

    result = await db.execute(
        select(QAHistory)
        .where(*filters)
        .order_by(QAHistory.created_at.desc())
        .limit(limit)
    )
    records = list(reversed(result.scalars().all()))  # 倒序取最近 → 正序注入

    history: list[dict] = []
    for r in records:
        history.append({"role": "user", "content": r.question or ""})
        ans = (r.answer or "").strip()
        # 历史来自 DB（未存思考过程），且这些是完整问答轮（无工具调用）。
        # DeepSeek 文档：无工具调用的 assistant 轮次 reasoning_content 无需
        # 参与上下文拼接（传入会被忽略）；且 thinking 已显式关闭（pipeline 治理），
        # 不需要也不应该塞占位文本——占位会被模型误读为真实思考内容展示给用户。
        history.append({"role": "assistant", "content": ans[: _HISTORY_ANSWER_MAX]})
    return history


def _transform_event(event: dict) -> dict:
    """将 loop 内部事件字段映射为 SSE 协议字段（Spec SSE 事件协议）。

    loop.py 内部用 {name, arguments, result}，
    SSE 协议要求 {tool_name, args, summary, detail}。
    返回新 dict 时透传 envelope 附加的所有权元数据（protocol_version/turn_id/
    sequence），否则前端按 turn_id/sequence 过滤的契约失效。
    """
    etype = event.get("type")
    env_meta = {
        k: v
        for k, v in event.items()
        if k in {"protocol_version", "event_type", "turn_id", "sequence"}
    }

    if etype == "tool_call":
        return {
            **env_meta,
            "type": "tool_call",
            "id": event.get("id"),
            "tool_name": event.get("name"),
            "args": event.get("arguments"),
        }

    if etype == "tool_result":
        result_text = event.get("result", "")
        return {
            **env_meta,
            "type": "tool_result",
            "id": event.get("id"),
            "tool_name": event.get("name"),
            "summary": result_text[:_RESULT_SUMMARY_MAX],
            "detail": result_text,
        }

    if etype == "tool_error":
        return {
            **env_meta,
            "type": "tool_error",
            "id": event.get("id"),
            "tool_name": event.get("name"),
            "error": event.get("error"),
            "retryable": event.get("retryable", True),
        }

    if etype == "usage":
        usage = event.get("usage", {})
        return {
            **env_meta,
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
    record.process_trace = db_trace  # 行 459: 完整 prompt 进 DB
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
    tool_hint: str | None = None,
    turn_id: str | None = None,
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
    - agent_done: Agent 完成（answer, qa_id, process_trace, token_usage）
    - quota_exceeded: 配额不足（message）
    - error: 内部错误（message）

    Yields:
        dict: SSE 事件
    """
    queue: asyncio.Queue = asyncio.Queue()
    loop_result: ReactLoopResult | None = None
    loop_error: Exception | None = None
    start_time = time.monotonic()  # Spec: 紧凑摘要含耗时
    turn_id = turn_id or uuid.uuid4().hex
    sequence = 0

    def envelope(event: dict) -> dict:
        """Attach stable stream ownership metadata to every emitted event."""
        nonlocal sequence
        sequence += 1
        from services.react_agent.events import PROTOCOL_VERSION

        return {
            **event,
            "protocol_version": PROTOCOL_VERSION,
            "event_type": event.get("type", "unknown"),
            "turn_id": event.get("turn_id", turn_id),
            "sequence": sequence,
        }

    async def event_callback(event: dict) -> None:
        """react_loop 事件回调 — 入队 transport-neutral raw event。"""
        await queue.put(event)

    async def run_loop() -> None:
        """后台运行 react_loop，结束后放入 SENTINEL 标记完成。"""
        nonlocal loop_result, loop_error
        try:
            # 多轮上下文注入：加载该对话（或该简历）最近几轮完整问答传给 react_loop，
            # 让 Agent 能看到上一轮结论（如"方案 A/B"）——修复"会话记忆不进入上下文"
            try:
                history = await _load_conversation_history(
                    db, user_id, resume_id, conversation_id
                )
            except Exception:
                # 历史加载失败（如测试用 mock db / 查询异常）降级为空，不阻断主流程
                logger.warning("多轮历史加载失败，降级为空（不影响回答）", exc_info=True)
                history = []
            # 注：checkpoint_key / inject_key 在生成器作用域计算（见函数入口），
            # 此处通过闭包读取后透传给 react_loop，保持 key 结构与注入端点一致。
            loop_result = await react_loop(
                db=db,
                user_id=user_id,
                resume_id=resume_id,
                question=question,
                history=history,
                event_callback=event_callback,
                tool_mode=tool_mode,
                tool_hint=tool_hint,
                checkpoint_key=checkpoint_key,
                inject_key=inject_key,
            )
        except Exception as e:
            loop_error = e
            logger.error("react_loop 异常: %s", e, exc_info=True)
        finally:
            await queue.put(_SENTINEL)

    # 回合 checkpoint 与回合注入队列共用 key 结构。
    # 定义在生成器作用域（而非 run_loop）——run_loop 的局部变量对外层不可见，
    # 若在 run_loop 内赋值，下方回合结束清理注入队列时会抛 NameError。
    checkpoint_key = None
    inject_key = None
    if tool_mode == "agent":
        conv_suffix = conversation_id if conversation_id else "all"
        checkpoint_key = (
            f"react:checkpoint:{user_id}:{resume_id}:{conv_suffix}"
        )
        inject_key = (
            f"react:inject:{user_id}:{resume_id}:{conv_suffix}"
        )

    active_key = f"react:active:{user_id}:{resume_id}:{conversation_id or 'all'}"
    try:
        from core.redis_client import get_redis
        _active_redis = await get_redis()
        if _active_redis is not None:
            await _active_redis.setex(active_key, 1800, turn_id)
    except Exception:
        _active_redis = None

    async def cleanup_active_key() -> None:
        if _active_redis is not None:
            try:
                current = await _active_redis.get(active_key)
                if isinstance(current, bytes):
                    current = current.decode("utf-8", errors="ignore")
                if current == turn_id:
                    script = "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) else return 0 end"
                    if hasattr(_active_redis, "eval"):
                        await _active_redis.eval(script, 1, active_key, turn_id)
                    else:
                        # Without atomic eval, retain short TTL rather than race-delete a newer turn.
                        logger.debug("Redis lacks eval; retain active key until TTL")
            except Exception:
                logger.debug("清理活跃回合标记失败", exc_info=True)

    task = asyncio.create_task(run_loop())

    try:
        # ── 等待第一个事件 — 判断配额是否通过 ──────────────────
        first_event = await queue.get()

        # 异常情况：loop 在发出任何事件前就结束了
        if first_event is _SENTINEL:
            await cleanup_active_key()
            if loop_error:
                yield envelope({"type": "error", "message": "Agent 处理失败，请重试"})
            else:
                yield envelope({"type": "error", "message": "Agent 未产出任何事件"})
            return

        # 配额不足 → 不创建占位记录，直接返回
        if first_event.get("type") == "quota_exceeded":
            await cleanup_active_key()
            yield envelope(first_event)
            await queue.get()  # 消费 SENTINEL
            await task
            return

        # ── 通知前端 Agent 开始（先发首事件，不被占位记录 DB 写阻塞）──
        yield envelope({
            "type": "agent_start",
            "resume_id": resume_id,
            "turn_id": turn_id,
            "tools": _get_tool_list(tool_mode),
        })
        logger.info(
            "agent_sse first_event_ms=%d", int((time.monotonic() - start_time) * 1000)
        )

        # ── 创建占位记录（agent_start 已发出，前端已响应）────────
        placeholder = await save_qa_placeholder(db, user_id, resume_id, question, conversation_id)
        qa_id = placeholder.id

        # 转发第一个事件（agent_done 由末尾统一处理）
        if first_event.get("type") != "agent_done":
            yield envelope(_transform_event(first_event))

        # ── 持续转发中间事件（字段映射为 SSE 协议） ──────────
        while True:
            event = await queue.get()
            if event is _SENTINEL:
                break
            if event.get("type") == "quota_exceeded":
                # quota 是 terminal：先发送，再正常 drain 后台 loop，禁止同 turn
                # 的后续 agent_done/error 成为第二个 terminal。
                yield envelope(_transform_event(event))
                while await queue.get() is not _SENTINEL:
                    pass
                await task
                await cleanup_active_key()
                try:
                    from services.qa_service import mark_qa_interrupted

                    await mark_qa_interrupted(
                        db,
                        qa_id,
                        answer=event.get("message", "额度不足，生成已终止"),
                    )
                except Exception:
                    logger.warning("标记 quota 终止 QA 记录失败: qa_id=%s", qa_id)
                return
            # agent_done 从 callback 来的只有 content，
            # 由末尾补充 qa_id + process_trace 后统一 yield
            if event.get("type") == "agent_done":
                continue
            yield envelope(_transform_event(event))

        await task

        # 回合结束清理注入队列（残留消息不污染下一回合）
        await cleanup_active_key()

        # ── 检查异常 ──────────────────────────────────────────
        if loop_error:
            await cleanup_active_key()
            # 失败也落库（status=failed + 错误信息），前端可展示重试入口
            # （用户反馈：失败/错误的聊天记录不存库、无聊天记录）
            try:
                from services.qa_service import mark_qa_interrupted

                await mark_qa_interrupted(
                    db, qa_id, answer=f"⚠️ Agent 执行出错：{loop_error}"
                )
            except Exception:
                logger.warning("标记失败 QA 记录失败: qa_id=%s", qa_id)
            yield envelope({"type": "error", "message": f"Agent 执行出错: {loop_error}"})
            return

        if loop_result is None:
            await cleanup_active_key()
            try:
                from services.qa_service import mark_qa_interrupted

                await mark_qa_interrupted(
                    db, qa_id, answer="⚠️ Agent 未返回结果，请重试"
                )
            except Exception:
                logger.warning("标记失败 QA 记录失败: qa_id=%s", qa_id)
            yield envelope({"type": "error", "message": "Agent 未返回结果"})
            return

        # ── 更新 QA 记录（完整 prompt trace 存 DB） ──────────
        sources = getattr(loop_result, "sources", [])  # : search_resume 来源聚合
        await update_qa_answer(
            db=db,
            qa_id=qa_id,
            answer=loop_result.answer,
            sources=sources,
            token_usage=loop_result.usage,
            db_trace=loop_result.db_trace,  # 行 459: 完整 prompt 进 DB
        )

        # ── 记录 quota 消耗（analytics 已由 llm_generate_with_tools_stream 内部 record_llm_usage 完成，
        # 此处仅记录 quota 消耗，与传统 RAG 路径对齐） ──────
        pt = loop_result.usage.get("prompt_tokens", 0)
        ct = loop_result.usage.get("completion_tokens", 0)
        if pt > 0 or ct > 0:
            from services.token_quota import record_usage as _record_quota
            await _record_quota(user_id, pt, ct)

        # ── 记忆提炼（后台 fire-and-forget，节流触发写 L4） ────
        # 仅 Agent 问答路径（tool_mode != "builder"）；开关默认关，测试零污染。
        # 此处置于 update_qa_answer 之后、agent_done 之前：若消费端在 agent_done
        # 前断连，此段抛 CancelledError 走下方异常分支，天然不提炼（不完整回合不沉淀记忆）。
        if settings.MEMORY_EXTRACTION_ENABLED and tool_mode != "builder":
            try:
                from services.memory.extraction_trigger import maybe_extract_memories

                asyncio.create_task(
                    maybe_extract_memories(
                        user_id=user_id,
                        conversation_text=f"用户：{question}\nAI：{loop_result.answer}",
                    )
                )
            except Exception:
                logger.warning("记忆提炼调度失败（不影响主流程）", exc_info=True)

        # ── 产出最终 agent_done 事件（ 字段对齐） ────────
        # SSE done.process_trace = 紧凑摘要（轮数/工具序列/耗时），非全量事件列表
        duration_ms = int((time.monotonic() - start_time) * 1000)
        logger.info("agent_sse done_ms=%d", duration_ms)
        compact_trace = _build_compact_trace(loop_result.process_trace, duration_ms)
        yield envelope({
            "type": "agent_done",
            "answer": loop_result.answer,
            "qa_id": qa_id,
            "sources": sources,
            "token_usage": loop_result.usage,
            "process_trace": compact_trace,
            "degraded": _has_tool_error(loop_result.process_trace),
        })

    except (asyncio.CancelledError, GeneratorExit) as e:
        # 客户端断连 — 取消后台 task，占位记录标记为 failed（生成中断），
        # 不再保留 status=streaming 的空记录（否则返回后历史会加载出"空记录"污染聊天）。
        # GeneratorExit：浏览器关闭/切页断开 SSE 时 async generator 收到的是
        # GeneratorExit 而非 CancelledError——漏处理会残留 status=streaming 记录
        # （实测浏览器断连残留，用户反馈「中途切换页面不会继续输出」的落库侧根因）。
        logger.info(
            "Client disconnected from agent stream: user=%d, resume=%d, exc=%s",
            user_id,
            resume_id,
            type(e).__name__,
        )
        await cleanup_active_key()
        if not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        # 标记占位记录为"生成中断"（存在则更新；不阻塞断连流程）
        if "qa_id" in locals() and qa_id:
            try:
                from services.qa_service import mark_qa_interrupted

                await mark_qa_interrupted(db, qa_id)
            except Exception:
                logger.warning("标记中断 QA 记录失败: qa_id=%s", qa_id)
        # GeneratorExit 必须继续传播（不能吞掉生成器关闭信号）
        if isinstance(e, GeneratorExit):
            raise
        raise
    except Exception as e:
        logger.error("agent stream 未处理异常: %s", e, exc_info=True)
        await cleanup_active_key()
        if not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        if "qa_id" in locals() and qa_id:
            try:
                await db.rollback()
            except Exception:
                logger.warning("异常 QA 补偿前 rollback 失败: qa_id=%s", qa_id)
            try:
                from services.qa_service import mark_qa_interrupted

                await mark_qa_interrupted(
                    db,
                    qa_id,
                    answer="⚠️ Agent 处理失败，请重试",
                )
            except Exception:
                logger.warning("标记异常 QA 记录失败: qa_id=%s", qa_id)
        yield envelope({"type": "error", "message": "Agent 处理失败，请重试"})


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


# ═══════════════════════════════════════════════════════════════
# 中断消息注入 + 压缩后恢复用户消息
# ═══════════════════════════════════════════════════════════════


@dataclass
class InterruptRecord:
    """中断记录。"""

    reason: str
    timestamp: float
    session_key: str
    pending: bool = True


class InterruptHandler:
    """中断处理器：记录中断原因 + 生成注入消息。

    断连/异常时 record_interrupt 记录；checkpoint 恢复后
    get_interrupt_message 生成 turn_aborted 风格提示，让 LLM
    感知上一轮被中断、工具可能部分执行。
    """

    def __init__(self) -> None:
        self._pending: list[InterruptRecord] = []

    def record_interrupt(self, reason: str, session_key: str) -> None:
        """记录中断（内存队列，最新优先，最多保留 5 条）。"""
        self._pending.append(
            InterruptRecord(
                reason=reason,
                timestamp=time.time(),
                session_key=session_key,
                pending=True,
            )
        )
        if len(self._pending) > 5:
            self._pending = self._pending[-5:]

    def get_interrupt_message(self) -> str | None:
        """生成中断提示消息（消费后清空 pending）。"""
        pending = [r for r in self._pending if r.pending]
        if not pending:
            return None
        for r in pending:
            r.pending = False
        reasons = "; ".join(r.reason for r in pending[-3:])
        return (
            "<turn_aborted>\n"
            "上一轮对话被中断（原因: " + reasons + "）。任何正在运行的后台进程"
            "可能仍在活动；已执行的工具可能部分完成。\n"
            "</turn_aborted>"
        )


class UserMessageRestorer:
    """压缩后恢复用户原始问题。

    L1 结构化压缩后用户消息可能被摘要 handoff 顶掉，模型会误解上下文。
    该工具确保用户当前问题始终在消息列表末尾，避免"模型答非所问"。
    """

    @staticmethod
    def should_restore(messages: list[dict], user_message: str | None) -> bool:
        """是否需要恢复用户消息。"""
        if not user_message or not user_message.strip():
            return False
        if not messages:
            return True
        # 最后一条是用户消息且内容一致 → 无需恢复
        last = messages[-1]
        if last.get("role") == "user" and last.get("content") == user_message:
            return False
        return True

    @staticmethod
    def restore(messages: list[dict], user_message: str | None) -> list[dict]:
        """恢复用户消息到消息列表末尾（幂等）。"""
        if not UserMessageRestorer.should_restore(messages, user_message):
            return messages
        messages.append({"role": "user", "content": user_message})
        return messages
