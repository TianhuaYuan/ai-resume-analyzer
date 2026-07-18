import json
import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_current_user
from core.config import settings
from core.database import get_db
from core.limiter import limiter
from core.security import detect_prompt_injection, redact_pii
from models.user import User
from schemas.qa import AnswerResponse, QuestionRequest, QAHistoryResponse
from services import qa_service, resume_service
from services.rag.pipeline import ask_question_stream

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/qa", tags=["qa"])


def _guard_question(question: str) -> None:
    """SEC-008：用户问题进模型前的"话术安检"，命中注入模板即拒绝（422）。"""
    suspicious, reason = detect_prompt_injection(question)
    if suspicious:
        logger.warning("检测到疑似提示注入，已拒绝: %s", reason)
        from fastapi import HTTPException, status

        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="问题含疑似提示注入内容，已拒绝处理",
        )


# ── 阶段4 错误透传：Agentic RAG 图接入 ──────────────────────
# 外部对 agentic 流程的调用统一走这里（README 规划的 run_agentic_rag 入口，
# 但 rag_service 属阶段1 受保护文件，故编排放在本文件内）。
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
    # SEC-008：用户问题进模型前先过注入安检
    _guard_question(data.question)
    await resume_service.get_resume(db, data.resume_id, current_user.id)
    answer, sources, tool_errors = await _run_agentic_rag(data.resume_id, data.question)
    # SEC-010：按配置对 LLM 输出做 PII 脱敏（默认关，避免误伤简历正常内容）
    if settings.REDACT_PII_OUTPUT:
        answer = redact_pii(answer)
    degraded = bool(tool_errors)
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
        degraded=degraded,
    )


@router.post("/ask/stream")
@limiter.limit(settings.RATE_LIMIT_ASK)
async def ask_question_stream(
    request: Request,
    data: QuestionRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """SSE 流式问答。先检索→再逐 token 推送生成内容。"""
    # SEC-008：流式路径同样先过注入安检
    _guard_question(data.question)
    await resume_service.get_resume(db, data.resume_id, current_user.id)

    async def event_stream():
        full_answer = ""
        sources_texts: list[str] = []
        try:
            async for event in ask_question_stream(data.resume_id, data.question):
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
