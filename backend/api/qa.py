import asyncio
import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_current_user
from core.config import settings
from core.database import get_db
from core.limiter import limiter
from core.security import detect_prompt_injection, redact_pii
from models.user import User
from schemas.qa import AnswerResponse, QADeleteResponse, QuestionRequest, QAHistoryResponse
from services import qa_service, resume_service
from services.rag.pipeline import ask_question_stream as _ask_question_stream


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

_AGENTIC_GRAPH = None


def _get_agentic_graph():
    """懒加载并缓存编译好的 Agentic RAG 图（避免模块导入期重依赖）。"""
    global _AGENTIC_GRAPH
    if _AGENTIC_GRAPH is None:
        from services.agentic_rag.graph import create_agentic_rag_graph

        _AGENTIC_GRAPH = create_agentic_rag_graph()
    return _AGENTIC_GRAPH


async def _run_agentic_rag(resume_id: int, question: str) -> tuple[str, list[dict], list[dict]]:
    """跑 Agentic RAG 图，返回 (answer, sources, tool_errors)。

    - answer: 最终答案文本
    - sources: 生成节点抽出的来源列表 [{text, section, chunk_index, rerank_score}, ...]
    - tool_errors: 检索/重排子步骤中累加的失败记录；非空即「部分降级」
    """
    import uuid

    graph = _get_agentic_graph()
    initial_state = {
        "question": question,
        "resume_id": resume_id,
        "rewritten_query": "",
        "route_decision": "search",
        "chunks": [],
        "search_round": 0,
        "answer": "",
        "sources": [],
        "eval_score": 0.0,
        "eval_feedback": "",
        "should_retry": False,
        "completeness_score": 0.0,
        "accuracy_score": 0.0,
        "source_credibility_score": 0.0,
        "reflection_result": "",
        "missing_info": [],
        "supplement_queries": [],
        "reflection_round": 0,
        "final_answer": "",
        "final_sources": [],
        "trace": {},
        "tool_errors": [],
    }
    result = await graph.ainvoke(
        initial_state,
        config={"configurable": {"thread_id": str(uuid.uuid4())}},
    )
    answer = result.get("final_answer") or result.get("answer", "")
    sources = result.get("sources", []) or []
    tool_errors = result.get("tool_errors", []) or []
    return answer, sources, tool_errors


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
    )
    return AnswerResponse(
        id=record.id,
        question=record.question,
        answer=record.answer,
        sources=[s["text"] for s in record.sources or []],
        created_at=record.created_at,
        degraded=degraded,
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

    if mode == "agentic":
        answer, sources, tool_errors = await _run_agentic_rag(data.resume_id, data.question)
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
        try:
            full_answer = ""
            sources_texts: list[str] = []
            try:
                async for event in _ask_question_stream(data.resume_id, data.question):
                    if event["type"] == "done":
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
                        )
                        sources_texts = [s["text"] for s in sources_data]
                        yield f"data: {json.dumps({'type': 'done', 'sources': sources_texts, 'qa_id': record.id}, ensure_ascii=False)}\n\n"
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


@router.get("/history/{resume_id}", response_model=QAHistoryResponse)
async def get_history(
    resume_id: int,
    limit: int = Query(20, ge=1, le=100, description="每页数量，1-100"),
    offset: int = Query(0, ge=0, description="偏移量，>=0"),
    keyword: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """分页查某份简历的问答历史。

    可选 keyword 参数：在 question / answer 上做模糊匹配（不区分大小写）。
    空字符串或 None → 不过滤。

    P1-16: limit/offset 加上限校验，防止恶意大请求拉取全量数据。
    """
    await resume_service.get_resume(db, resume_id, current_user.id)
    items, total = await qa_service.get_history(
        db, current_user.id, resume_id, limit, offset, keyword=keyword
    )
    return QAHistoryResponse(
        items=[
            AnswerResponse(
                id=it.id,
                question=it.question,
                answer=it.answer,
                sources=[s["text"] for s in (it.sources or [])],
                created_at=it.created_at,
            )
            for it in items
        ],
        total=total,
    )


@router.delete("/history/{resume_id}", response_model=QADeleteResponse)
async def delete_history(
    resume_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """清空指定简历的所有问答历史。

    归属校验：resume_id 必须属于当前用户（不存在或非本人 → 404）。
    返回被删除的记录数。
    """
    await resume_service.get_resume(db, resume_id, current_user.id)
    deleted_count = await qa_service.delete_history_by_resume(db, current_user.id, resume_id)
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
