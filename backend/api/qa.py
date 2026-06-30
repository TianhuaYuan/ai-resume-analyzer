from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_current_user
from core.database import get_db
from models.user import User
from schemas.qa import AnswerResponse, QuestionRequest, QAHistoryResponse
from services import qa_service, rag_service, resume_service

router = APIRouter(prefix="/api/qa", tags=["qa"])


@router.post("/ask", response_model=AnswerResponse)
async def ask_question(
    data: QuestionRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """对简历提问。Query 改写 → 混合检索 → LLM 生成 → 存历史。"""
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
    return QAHistoryResponse(items=items, total=total)
