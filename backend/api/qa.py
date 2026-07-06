import json
import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_current_user
from core.database import get_db
from core.limiter import limiter
from models.user import User
from schemas.qa import AnswerResponse, QuestionRequest, QAHistoryResponse
from services import qa_service, rag_service, resume_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/qa", tags=["qa"])


@router.post("/ask", response_model=AnswerResponse)
@limiter.limit("20/minute")
async def ask_question(
    request: Request,
    data: QuestionRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """对简历提问。Query 改写 → 混合检索 → Rerank → LLM 生成 → 存历史。"""
    await resume_service.get_resume(db, data.resume_id, current_user.id)
    answer, sources = await rag_service.ask_question(data.resume_id, data.question)
    record = await qa_service.save_qa(
        db,
        current_user.id,
        data.resume_id,
        data.question,
        answer,
        [{"chunk_id": s["chunk_index"], "text": s["text"], "section": s["section"]} for s in sources],
    )
    return AnswerResponse(
        id=record.id,
        question=record.question,
        answer=record.answer,
        sources=[s["text"] for s in record.sources or []],
        created_at=record.created_at,
    )


@router.post("/ask/stream")
@limiter.limit("20/minute")
async def ask_question_stream(
    request: Request,
    data: QuestionRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """SSE 流式问答。先检索→再逐 token 推送生成内容。"""
    await resume_service.get_resume(db, data.resume_id, current_user.id)

    async def event_stream():
        full_answer = ""
        sources_texts: list[str] = []
        try:
            async for event in rag_service.ask_question_stream(data.resume_id, data.question):
                if event["type"] == "done":
                    full_answer = event.get("answer", "")
                    sources_data = event.get("sources", [])
                    # sources_data 现在是 [{"chunk_index":..., "text":..., "section":...}]
                    sources_for_db = [
                        {"chunk_id": s.get("chunk_index", i), "text": s["text"], "section": s.get("section", "")}
                        for i, s in enumerate(sources_data)
                    ]
                    record = await qa_service.save_qa(
                        db, current_user.id, data.resume_id,
                        data.question, full_answer, sources_for_db,
                    )
                    sources_texts = [s["text"] for s in sources_data]
                    yield f"data: {json.dumps({'type': 'done', 'sources': sources_texts, 'qa_id': record.id}, ensure_ascii=False)}\n\n"
                else:
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        except Exception as e:
            logger.error("SSE stream error: %s", e)
            yield f"data: {json.dumps({'type': 'error', 'message': '生成失败，请重试'}, ensure_ascii=False)}\n\n"

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
    limit: int = 20,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """分页查某份简历的问答历史。"""
    await resume_service.get_resume(db, resume_id, current_user.id)
    items, total = await qa_service.get_history(
        db, current_user.id, resume_id, limit, offset
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
