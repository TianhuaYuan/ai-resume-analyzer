import asyncio
import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_current_user
from core.config import settings
from core.database import get_db
from core.limiter import limiter
from core.security import detect_prompt_injection, redact_pii
from models.user import User
from schemas.feedback import QAFeedbackRequest
from schemas.qa import (
    AnswerResponse,
    ConversationCreateRequest,
    ConversationDeleteResponse,
    ConversationListResponse,
    ConversationRenameRequest,
    ConversationResponse,
    QADeleteResponse,
    QuestionRequest,
    QAHistoryResponse,
    TokenUsage,
)
from services import qa_service, resume_service
from services.feedback_service import submit_qa_feedback
from services.rag.asset_source import ASSET_TYPE_RESUME
from services.rag.clients import knowledge_collection_name
from services.rag.ensure_indexed import ensure_indexed
from services.rag.pipeline import ask_question_stream as _ask_question_stream
from services.react_agent.streaming import react_loop_stream
from services.token_quota import check_quota, record_usage, get_quota_status


class QuotaResponse(BaseModel):
    """Token 限额状态响应。"""
    enabled: bool
    used: int
    limit: int
    remaining: int
    reset_at: str | None


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/qa", tags=["qa"])


def _guard_question(question: str) -> None:
    """用户问题进模型前的"话术安检"，命中注入模板即拒绝（422）。"""
    suspicious, reason = detect_prompt_injection(question)
    if suspicious:
        logger.warning("检测到疑似提示注入，已拒绝: %s", reason)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="问题含疑似提示注入内容，已拒绝处理",
        )

async def _run_agentic_rag(user_id: int, resume_id: int, question: str) -> tuple[str, list[dict], list[dict]]:
    """跑 Agentic RAG 图，返回 (answer, sources, tool_errors)。

    收敛到 run_answer_from_index（T11 统一入口，单简历 = scope 只含该简历）。
    - sources: 生成节点抽出的 per-asset 来源列表
    - tool_errors: 检索/重排子步骤中累加的失败记录；非空即「部分降级」
    """
    from services.agentic_rag.runner import run_answer_from_index

    result = await run_answer_from_index(
        user_id=user_id,
        scope={ASSET_TYPE_RESUME: [resume_id]},
        question=question,
    )
    return result["answer"], result["sources"], result["tool_errors"]


@router.post("/ask", response_model=AnswerResponse)
@limiter.limit(settings.RATE_LIMIT_ASK)
async def ask_question(
    request: Request,
    data: QuestionRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """对简历提问。走 Agentic RAG 图（改写→检索→重排→生成→评估），
    若检索/重排存在失败则置 degraded，让前端提示『答案基于部分信息』。"""
    #用户问题进模型前先过注入安检
    _guard_question(data.question)
    await resume_service.get_resume(db, data.resume_id, current_user.id)
    # T6 懒索引：首次问答触发重建（脏标记 content_hash != indexed_hash）
    await ensure_indexed(
        db,
        user_id=current_user.id,
        asset_id=data.resume_id,
        asset_type=ASSET_TYPE_RESUME,
        collection=knowledge_collection_name(current_user.id),
    )
    answer, sources, tool_errors = await _run_agentic_rag(data.resume_id, data.question)
    # 按配置对 LLM 输出做 PII 脱敏（默认关，避免误伤简历正常内容）
    if settings.REDACT_PII_OUTPUT:
        answer = redact_pii(answer)
    degraded = bool(tool_errors)
    record = await qa_service.save_qa(
        db,
        current_user.id,
        data.resume_id,
        data.question,
        answer,
        [
            {"chunk_id": s["chunk_index"], "text": s["text"], "section": s["section"]}
            for s in sources
        ],
        conversation_id=data.conversation_id,
    )
    token_total = 0
    if answer and answer != "分析失败，请稍后重试":
        token_total = len(answer) // 2  # 简单估算
    return AnswerResponse(
        id=record.id,
        question=record.question,
        answer=record.answer,
        sources=[s.get("text", "") for s in record.sources or []],
        created_at=record.created_at,
        degraded=degraded,
        token_usage=TokenUsage(total=token_total),
    )


@router.post("/ask/stream")
@limiter.limit(settings.RATE_LIMIT_ASK)
async def ask_question_stream(
    request: Request,
    data: QuestionRequest,
    mode: str = "stream",
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """SSE 流式问答。

    mode=stream（默认）：走普通 RAG 流式管线，逐 token 推送。
    mode=agentic：走完整 Agentic RAG 图（改写→检索→重排→生成→评估→反思），
                  完成后一次性推送完整答案。
    """
    _guard_question(data.question)
    await resume_service.get_resume(db, data.resume_id, current_user.id)
    # T6 懒索引：首次问答触发重建（脏标记 content_hash != indexed_hash）
    await ensure_indexed(
        db,
        user_id=current_user.id,
        asset_id=data.resume_id,
        asset_type=ASSET_TYPE_RESUME,
        collection=knowledge_collection_name(current_user.id),
    )

    # Token 限额预检查
    allowed, quota_error = await check_quota(current_user.id)
    if not allowed:
        # 返回友好的限额提示（流式）
        async def quota_exceeded():
            yield f"data: {json.dumps({'type': 'error', 'message': quota_error, 'code': 'quota_exceeded'}, ensure_ascii=False)}\n\n"
        return StreamingResponse(
            quota_exceeded(),
            media_type="text/event-stream",
        )

    if mode == "agentic":
        answer, sources, tool_errors = await _run_agentic_rag(current_user.id, data.resume_id, data.question)
        if settings.REDACT_PII_OUTPUT:
            answer = redact_pii(answer)
        degraded = bool(tool_errors)
        sources_texts = [s.get("text", "") for s in sources]
        sources_for_db = [
            {
                "chunk_id": s.get("chunk_index", i),
                "text": s.get("text", ""),
                "section": s.get("section", ""),
            }
            for i, s in enumerate(sources)
        ]

        async def agentic_stream():
            from core.database import AsyncSessionLocal
            stream_db = AsyncSessionLocal()
            try:
                yield f"data: {json.dumps({'type': 'status', 'message': '分析完成'}, ensure_ascii=False)}\n\n"
                yield f"data: {json.dumps({'type': 'token', 'content': answer}, ensure_ascii=False)}\n\n"
                record = await qa_service.save_qa(
                    stream_db,
                    current_user.id,
                    data.resume_id,
                    data.question,
                    answer,
                    sources_for_db,
                    conversation_id=data.conversation_id,
                )
                yield f"data: {json.dumps({'type': 'done', 'answer': answer, 'sources': sources_texts, 'qa_id': record.id, 'degraded': degraded}, ensure_ascii=False)}\n\n"
            except Exception as e:
                logger.error("Agentic stream error: %s", e)
                yield f"data: {json.dumps({'type': 'error', 'message': '生成失败，请重试'}, ensure_ascii=False)}\n\n"
            finally:
                await stream_db.close()

        return StreamingResponse(
            agentic_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    async def event_stream():
        from core.database import AsyncSessionLocal
        stream_db = AsyncSessionLocal()
        prompt_tokens = 0
        completion_tokens = 0
        try:
            full_answer = ""
            sources_texts: list[str] = []
            try:
                async for event in _ask_question_stream(data.resume_id, data.question, user_id=current_user.id):
                    if event["type"] == "usage":
                        # 捕获 token 使用量
                        prompt_tokens = event.get("prompt_tokens", 0)
                        completion_tokens = event.get("completion_tokens", 0)
                        continue
                    elif event["type"] == "done":
                        full_answer = event.get("answer", "")
                        sources_data = event.get("sources", [])
                        sources_for_db = [
                            {
                                "chunk_id": s.get("chunk_index", i),
                                "text": s["text"],
                                "section": s.get("section", ""),
                            }
                            for i, s in enumerate(sources_data)
                        ]
                        record = await qa_service.save_qa(
                            stream_db,
                            current_user.id,
                            data.resume_id,
                            data.question,
                            full_answer,
                            sources_for_db,
                            conversation_id=data.conversation_id,
                        )
                        sources_texts = [s["text"] for s in sources_data]

                        # 记录 token 消耗
                        if prompt_tokens > 0 or completion_tokens > 0:
                            await record_usage(current_user.id, prompt_tokens, completion_tokens)

                        token_total = prompt_tokens + completion_tokens
                        yield f"data: {json.dumps({'type': 'done', 'sources': sources_texts, 'qa_id': record.id, 'token_usage': {'total': token_total, 'prompt': prompt_tokens, 'completion': completion_tokens}}, ensure_ascii=False)}\n\n"
                    else:
                        yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
            except asyncio.CancelledError:
                logger.info("Client disconnected, stopping LLM stream for user %d, resume %d", current_user.id, data.resume_id)
                raise
            except Exception as e:
                logger.error("SSE stream error: %s", e)
                yield f"data: {json.dumps({'type': 'error', 'message': '生成失败，请重试'}, ensure_ascii=False)}\n\n"
        finally:
            await stream_db.close()

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/ask/agent")
@limiter.limit(settings.RATE_LIMIT_ASK_AGENT)
async def ask_agent(
    request: Request,
    data: QuestionRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Agent SSE 流式问答。

    走 ReAct Agent 循环（工具调用 + 三层记忆 + 配额管理），
    实时推送事件：agent_start → tool_call → tool_result/tool_error → agent_done。

    独立限流（RATE_LIMIT_ASK_AGENT=8/min），与普通 /ask/stream 隔离。
    """
    _guard_question(data.question)
    await resume_service.get_resume(db, data.resume_id, current_user.id)

    # T19: 如果带 compare_ids，注入到问题上下文供 Agent 的 compare_resumes 工具使用
    effective_question = data.question
    if data.compare_ids:
        ids_str = ", ".join(str(i) for i in data.compare_ids)
        effective_question = f"{data.question}\n\n[可对比简历 ID: {ids_str}]"

    # v2: Builder 上下文注入（module_type/entry_id/action 拼接到问题中）
    if data.tool_mode == "builder" or data.module_type:
        builder_ctx_parts = []
        if data.module_type:
            builder_ctx_parts.append(f"目标模块: {data.module_type}")
        if data.entry_id:
            builder_ctx_parts.append(f"目标条目 ID: {data.entry_id}")
        if data.action:
            builder_ctx_parts.append(f"操作类型: {data.action}")
        if builder_ctx_parts:
            effective_question = f"{effective_question}\n\n[Builder 上下文: {' | '.join(builder_ctx_parts)}]"

    async def agent_stream():
        from core.database import AsyncSessionLocal

        stream_db = AsyncSessionLocal()
        try:
            async for event in react_loop_stream(
                db=stream_db,
                user_id=current_user.id,
                resume_id=data.resume_id,
                question=effective_question,
                tool_mode=data.tool_mode or "agent",
                conversation_id=data.conversation_id,
            ):
                # PII 脱敏（对 agent_done 的 answer）
                if event.get("type") == "agent_done" and settings.REDACT_PII_OUTPUT:
                    event["answer"] = redact_pii(event.get("answer", ""))

                # 记录 token 消耗
                if event.get("type") == "agent_done" and "usage" in event:
                    usage = event["usage"]
                    if usage.get("prompt_tokens", 0) > 0 or usage.get("completion_tokens", 0) > 0:
                        await record_usage(
                            current_user.id,
                            usage["prompt_tokens"],
                            usage["completion_tokens"],
                        )

                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        except asyncio.CancelledError:
            logger.info(
                "Client disconnected from agent stream: user=%d, resume=%d",
                current_user.id,
                data.resume_id,
            )
            raise
        except Exception as e:
            logger.error("Agent stream error: %s", e)
            yield f"data: {json.dumps({'type': 'error', 'message': 'Agent 处理失败，请重试'}, ensure_ascii=False)}\n\n"
        finally:
            await stream_db.close()

    return StreamingResponse(
        agent_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/ask/builder")
@limiter.limit(settings.RATE_LIMIT_ASK_AGENT)
async def ask_builder(
    request: Request,
    data: QuestionRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Builder Agent SSE 流式问答（已废弃，请使用 /ask/agent）。

    .. deprecated:: v2
        /ask/builder 已合并到 /ask/agent。保留此端点用于旧前端兼容。
        /ask/agent 现在支持 qa + builder 全部工具，通过 tool_mode="builder"
        或上下文中的 module_type/entry_id 自动识别 builder 场景。

    走 ReAct Agent 循环，实时推送事件：agent_start → tool_call → tool_result/tool_error → agent_done。
    """
    _guard_question(data.question)
    await resume_service.get_resume(db, data.resume_id, current_user.id)

    async def builder_stream():
        from core.database import AsyncSessionLocal

        stream_db = AsyncSessionLocal()
        try:
            async for event in react_loop_stream(
                db=stream_db,
                user_id=current_user.id,
                resume_id=data.resume_id,
                question=data.question,
                tool_mode="builder",
                conversation_id=data.conversation_id,
            ):
                # PII 脱敏
                if event.get("type") == "agent_done" and settings.REDACT_PII_OUTPUT:
                    event["answer"] = redact_pii(event.get("answer", ""))

                # 记录 token 消耗
                if event.get("type") == "agent_done" and "usage" in event:
                    usage = event["usage"]
                    if usage.get("prompt_tokens", 0) > 0 or usage.get("completion_tokens", 0) > 0:
                        await record_usage(
                            current_user.id,
                            usage["prompt_tokens"],
                            usage["completion_tokens"],
                        )

                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        except asyncio.CancelledError:
            logger.info(
                "Client disconnected from builder stream: user=%d, resume=%d",
                current_user.id,
                data.resume_id,
            )
            raise
        except Exception as e:
            logger.error("Builder stream error: %s", e)
            yield f"data: {json.dumps({'type': 'error', 'message': 'Builder 处理失败，请重试'}, ensure_ascii=False)}\n\n"
        finally:
            await stream_db.close()

    return StreamingResponse(
        builder_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/history/{resume_id}", response_model=QAHistoryResponse)
async def get_history(
    resume_id: int,
    limit: int = Query(20, ge=1, le=100, description="每页数量，1-100"),
    offset: int = Query(0, ge=0, description="偏移量，>=0"),
    keyword: str | None = None,
    conversation_id: int | None = Query(None, description="可选：按对话筛选"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """分页查某份简历（可选某对话）的问答历史。

    可选 keyword 参数：在 question / answer 上做模糊匹配（不区分大小写）。
    可选 conversation_id 参数：只查指定对话的问答。
    空字符串或 None → 不过滤。

    P1-16: limit/offset 加上限校验，防止恶意大请求拉取全量数据。
    """
    await resume_service.get_resume(db, resume_id, current_user.id)
    items, total = await qa_service.get_history(
        db,
        current_user.id,
        resume_id,
        limit,
        offset,
        keyword=keyword,
        conversation_id=conversation_id,
    )
    return QAHistoryResponse(
        items=[
            AnswerResponse(
                id=it.id,
                question=it.question,
                answer=it.answer,
                sources=[s.get("text", "") for s in (it.sources or [])],
                created_at=it.created_at,
            )
            for it in items
        ],
        total=total,
    )


@router.delete("/history/{resume_id}", response_model=QADeleteResponse)
async def delete_history(
    resume_id: int,
    conversation_id: int | None = Query(None, description="可选：只清空指定对话"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """清空指定简历（或指定对话）的所有问答历史。

    归属校验：resume_id 必须属于当前用户（不存在或非本人 → 404）。
    返回被删除的记录数。
    """
    await resume_service.get_resume(db, resume_id, current_user.id)
    deleted_count = await qa_service.delete_history_by_resume(
        db, current_user.id, resume_id, conversation_id=conversation_id,
    )
    return QADeleteResponse(deleted_count=deleted_count)


@router.delete("/{qa_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_qa(
    qa_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """删单条问答记录。

    user_id 隔离：非本人记录视为不存在（返回 404）。
    """
    deleted = await qa_service.delete_qa_by_id(db, current_user.id, qa_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="问答记录不存在或无权访问",
        )
    return None


# ── 对话会话 CRUD ─────────────────────────────────────────


@router.get("/conversations/{resume_id}", response_model=ConversationListResponse)
async def list_conversations(
    resume_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """列出某简历下的所有对话，按最近活跃降序排列。"""
    await resume_service.get_resume(db, resume_id, current_user.id)
    conversations = await qa_service.get_conversations(db, current_user.id, resume_id)
    items = []
    for conv in conversations:
        count = await qa_service.get_conversation_message_count(db, conv.id)
        items.append(
            ConversationResponse(
                id=conv.id,
                title=conv.title,
                created_at=conv.created_at,
                updated_at=conv.updated_at,
                message_count=count,
            )
        )
    return ConversationListResponse(items=items, total=len(items))


@router.post(
    "/conversations/{resume_id}",
    response_model=ConversationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_conversation(
    resume_id: int,
    data: ConversationCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """为指定简历创建新对话。"""
    await resume_service.get_resume(db, resume_id, current_user.id)
    conv = await qa_service.create_conversation(
        db, current_user.id, resume_id, data.title,
    )
    return ConversationResponse(
        id=conv.id,
        title=conv.title,
        created_at=conv.created_at,
        updated_at=conv.updated_at,
        message_count=0,
    )


@router.put("/conversations/{conversation_id}", response_model=ConversationResponse)
async def rename_conversation(
    conversation_id: int,
    data: ConversationRenameRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """重命名对话。"""
    conv = await qa_service.rename_conversation(
        db, current_user.id, conversation_id, data.title,
    )
    if conv is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="对话不存在或无权访问",
        )
    count = await qa_service.get_conversation_message_count(db, conv.id)
    return ConversationResponse(
        id=conv.id,
        title=conv.title,
        created_at=conv.created_at,
        updated_at=conv.updated_at,
        message_count=count,
    )


@router.delete(
    "/conversations/{conversation_id}",
    response_model=ConversationDeleteResponse,
)
async def delete_conversation(
    conversation_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """删除对话及其所有问答。"""
    deleted_count = await qa_service.delete_conversation(
        db, current_user.id, conversation_id,
    )
    if deleted_count is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="对话不存在或无权访问",
        )
    return ConversationDeleteResponse(deleted_count=deleted_count)


@router.get("/quota", response_model=QuotaResponse)
async def get_quota_status_api(
    current_user: User = Depends(get_current_user),
):
    """获取当前用户的 token 限额状态。

    前端可实时显示今日额度使用情况，env更新后自动生效（无需重启）。
    """
    return await get_quota_status(current_user.id)


@router.post("/{qa_id}/feedback", status_code=status.HTTP_204_NO_CONTENT)
async def create_qa_feedback(
    qa_id: int,
    data: QAFeedbackRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """对单条问答提交赞/踩反馈。

    - rating: "positive" | "negative"
    - 同一 qa_id 重复提交会覆盖旧反馈
    - 只能对自己的问答记录提交反馈
    """
    try:
        await submit_qa_feedback(
            db,
            user_id=current_user.id,
            qa_id=qa_id,
            rating=data.rating,
        )
    except LookupError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="问答记录不存在",
        )
    except PermissionError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="无权访问该问答记录",
        )
    return None
