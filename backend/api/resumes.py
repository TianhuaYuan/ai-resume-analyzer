import logging
import os

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Header,
    HTTPException,
    Query,
    Response,
    UploadFile,
    status,
)
from fastapi.responses import PlainTextResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_current_user
from core.database import get_db
from core.security import detect_prompt_injection
from models.resume import Resume
from models.user import User
from schemas.resume import (
    AnalyzeRequest,
    AnalyzeResponse,
    ChunkItem,
    ChunksResponse,
    CompareRequest,
    CompareResponse,
    MatchJDRequest,
    MatchJDResponse,
    ResumeListResponse,
    ResumeResponse,
    UploadAsyncResponse,
)
from services import analyze_service, match_jd_service, resume_service
from services.rag import chunks_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/resumes", tags=["resumes"])


async def _find_resume_by_idempotency_key(
    db: AsyncSession, user_id: int, idempotency_key: str
) -> Resume | None:
    """按 (用户, idempotency_key) 查已有简历，用于幂等去重。"""
    result = await db.execute(
        select(Resume).where(Resume.user_id == user_id, Resume.idempotency_key == idempotency_key)
    )
    return result.scalar_one_or_none()


def _guard_jd_text(jd_text: str) -> None:
    """P1-18: jd_text 进 LLM 前的注入安检，命中注入模板即拒绝（422）。

    jd_text 会拼进 user_prompt 发给 LLM，必须和 /qa/ask 的问题一样做注入安检，
    防止 "忽略以上指令" 之类的攻击劫持模型输出。
    """
    suspicious, reason = detect_prompt_injection(jd_text)
    if suspicious:
        logger.warning("检测到疑似提示注入，已拒绝: %s", reason)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="JD 文本含疑似提示注入内容，已拒绝处理",
        )


@router.post("", response_model=UploadAsyncResponse)
async def upload_resume(
    file: UploadFile = File(...),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    background: BackgroundTasks = None,  # type: ignore[assignment]
    response: Response = None,  # type: ignore[assignment]
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """上传简历（幂等）。

    带 Idempotency-Key 且当前用户已存在同 key 的简历时，直接返回已有记录（200），
    避免前端重试/网络抖动导致重复创建简历；否则新建（202）并异步解析+分块+向量化。

    P1-9: 应用层短路检查 + DB 层 UNIQUE 约束双重防御并发竞态。
    即使两个请求同时通过短路检查，DB UNIQUE 也会让第二个 commit 抛 IntegrityError，
    回滚后查已有记录返回，并清理本次写入的孤儿文件。

    注意：user_id 必须在 rollback 前提取为局部变量。rollback 会让 session 中所有
    ORM 对象 expired，之后访问 current_user.id 会触发 sync lazy load → MissingGreenlet。
    """
    user_id = current_user.id  # 提前提取，避免 rollback 后访问 expired 属性

    # ── 幂等短路：同 key 已存在 → 返回已有记录 ──
    if idempotency_key:
        existing = await _find_resume_by_idempotency_key(db, user_id, idempotency_key)
        if existing is not None:
            response.status_code = 200
            return UploadAsyncResponse(
                id=existing.id,
                filename=existing.filename,
                status=existing.status,
            )

    file_path, filename = await resume_service.save_upload_file(file)

    # P1-9: idempotency_key 与基本信息一起写入，触发 UNIQUE 约束兜底并发竞态
    try:
        resume = await resume_service.create_resume_quick(
            db, user_id, filename, file_path, idempotency_key=idempotency_key
        )
    except IntegrityError:
        # 并发竞态：另一个请求已先一步写入同 (user_id, idempotency_key) 的 resume
        await db.rollback()
        existing = await _find_resume_by_idempotency_key(db, user_id, idempotency_key)
        if existing is not None:
            # 清理本次写入的孤儿文件（避免文件系统残留）
            try:
                os.remove(file_path)
            except Exception:
                logger.warning("Failed to clean up orphan file: %s", file_path)
            response.status_code = 200
            return UploadAsyncResponse(
                id=existing.id,
                filename=existing.filename,
                status=existing.status,
            )
        # 罕见：IntegrityError 但查不到记录（如其他约束冲突）
        # 转成 HTTPException 500，避免裸 IntegrityError 冒泡到 middleware 层
        # （BaseHTTPMiddleware 场景下全局 Exception handler 捕获不可靠）
        logger.exception(
            "IntegrityError with no existing resume for idempotency_key=%s", idempotency_key
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="简历上传失败，请重试",
        )

    if background is not None:
        background.add_task(resume_service.process_resume_background, resume.id, file_path)

    response.status_code = 202
    return UploadAsyncResponse(
        id=resume.id,
        filename=resume.filename,
        status=resume.status,
    )


@router.get("", response_model=ResumeListResponse)
async def list_resumes(
    limit: int = Query(20, ge=1, le=100, description="每页数量，1-100"),
    offset: int = Query(0, ge=0, description="偏移量，>=0"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """分页查当前用户的简历列表。

    P1-16: limit/offset 加上限校验，防止恶意大请求拉取全量数据。
    """
    items, total = await resume_service.get_user_resumes(db, current_user.id, limit, offset)
    return ResumeListResponse(items=items, total=total)


@router.get("/{resume_id}", response_model=ResumeResponse)
async def get_resume(
    resume_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """查单份简历（含处理状态）。非本人→404。"""
    return await resume_service.get_resume(db, resume_id, current_user.id)


@router.delete("/{resume_id}", status_code=204)
async def delete_resume(
    resume_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """删简历。先删 MySQL（CASCADE 清历史）→ 清 Chroma → 删文件 → 清 Embedding 缓存。"""
    await resume_service.delete_resume(db, resume_id, current_user.id)
    return None


@router.post("/{resume_id}/retry", response_model=UploadAsyncResponse, status_code=status.HTTP_202_ACCEPTED)
async def retry_resume(
    resume_id: int,
    background: BackgroundTasks = None,  # type: ignore[assignment]
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """P1-24：手动重试失败的简历处理。

    仅 status=failed 的简历可重试。重试时把状态改回 processing，
    并重新触发后台解析 → 分块 → 向量化流程。

    错误码：
    - 401 未登录
    - 404 简历不存在或非本人
    - 409 简历状态不是 failed
    """
    resume = await resume_service.retry_resume_processing(db, resume_id, current_user.id)
    if background is not None:
        background.add_task(resume_service.process_resume_background, resume.id, resume.file_path)
    return UploadAsyncResponse(
        id=resume.id,
        filename=resume.filename,
        status=resume.status,
    )


@router.post("/{resume_id}/analyze", response_model=AnalyzeResponse)
async def post_analyze_resume(
    resume_id: int,
    body: AnalyzeRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """分析简历内容（summary / skills / experience 三选一）。

    包装 analyze_service.analyze_resume。错误码：
    - 401 未登录
    - 404 简历不存在或非本人
    - 409 简历未就绪（status != ready）
    - 422 非法 analysis_type（Pydantic Literal 拦截）或简历内容为空
    - 500 LLM 调用失败
    """
    result = await analyze_service.analyze_resume(
        db, current_user.id, resume_id, body.analysis_type
    )
    return AnalyzeResponse(**result)


@router.get("/{resume_id}/chunks", response_model=ChunksResponse)
async def get_resume_chunks(
    resume_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """查简历的所有分块（chunks）。

    归属校验走 MySQL，chunk 数据走 ChromaDB。
    错误码：
    - 401 未登录
    - 404 简历不存在或非本人
    - 409 简历未就绪（status != ready）或 Chroma collection 不存在
    """
    # 归属校验（不存在或非本人 → 404）
    resume = await resume_service.get_resume(db, resume_id, current_user.id)

    # 状态校验（未就绪 → 409）
    if resume.status != "ready":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"简历未就绪（当前状态: {resume.status}）",
        )

    # 读 ChromaDB（collection 不存在 → 409）
    chunks_data = await chunks_service.get_chunks_by_resume(resume_id)

    return ChunksResponse(
        resume_id=resume_id,
        total=len(chunks_data),
        chunks=[ChunkItem(**c) for c in chunks_data],
    )


@router.post("/{resume_id}/match-jd", response_model=MatchJDResponse)
async def post_match_jd(
    resume_id: int,
    body: MatchJDRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """将简历与 JD 文本进行匹配分析。

    返回 LLM 生成的匹配分数、匹配点、差距分析和改进建议。
    错误码：
    - 401 未登录
    - 404 简历不存在或非本人
    - 409 简历未就绪（status != ready）
    - 422 JD 文本为空、超长或含疑似提示注入
    - 500 LLM 调用失败
    """
    # P1-18: jd_text 进 LLM 前做注入安检（和 /qa/ask 的问题一样）
    _guard_jd_text(body.jd_text)
    result = await match_jd_service.match_jd(
        db, current_user.id, resume_id, body.jd_text
    )
    return MatchJDResponse(**result)


@router.get("/{resume_id}/export", response_class=PlainTextResponse)
async def export_resume(
    resume_id: int,
    export_format: str = "markdown",
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """导出简历分析报告。

    当前仅支持 export_format=markdown。
    返回包含简历原文 + 评分的 Markdown 报告。
    错误码：
    - 401 未登录
    - 404 简历不存在或非本人
    - 409 简历未就绪
    """
    resume = await resume_service.get_resume(db, resume_id, current_user.id)

    if resume.status != "ready":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"简历未就绪（当前状态: {resume.status}）",
        )

    if export_format != "markdown":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"不支持的导出格式: {export_format}，目前仅支持 markdown",
        )

    # 构建 Markdown 报告
    lines = [
        f"# 简历分析报告",
        "",
        f"**文件名**: {resume.filename}",
        f"**创建时间**: {resume.created_at.strftime('%Y-%m-%d %H:%M')}",
        f"**分块数量**: {resume.chunk_count}",
        "",
        "---",
        "",
        "## 简历原文",
        "",
        resume.parsed_text or "（空）",
        "",
        "---",
        "",
        "*报告由 AI Resume Analyzer 自动生成*",
    ]

    content = "\n".join(lines)
    # Content-Disposition 文件名只使用 ASCII 安全字符，中文用 resume_id 代替
    return PlainTextResponse(
        content=content,
        media_type="text/markdown; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="resume_{resume_id}_report.md"'
        },
    )


@router.post("/compare", response_model=CompareResponse)
async def compare_resumes(
    body: CompareRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """多简历对比分析。

    对比 2-5 份简历的技能和项目维度。
    错误码：
    - 401 未登录
    - 404 任一简历不存在或非本人
    - 422 resume_ids 或 dimensions 不符合规范
    """
    result = await resume_service.compare_resumes(
        db, current_user.id, body.resume_ids, body.dimensions
    )
    return CompareResponse(**result)
