from fastapi import APIRouter, BackgroundTasks, Depends, File, Header, Response, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_current_user
from core.database import get_db
from models.resume import Resume
from models.user import User
from schemas.resume import ResumeListResponse, ResumeResponse, UploadAsyncResponse
from services import resume_service

router = APIRouter(prefix="/resumes", tags=["resumes"])


async def _find_resume_by_idempotency_key(
    db: AsyncSession, user_id: int, idempotency_key: str
) -> Resume | None:
    """按 (用户, idempotency_key) 查已有简历，用于幂等去重。"""
    result = await db.execute(
        select(Resume).where(
            Resume.user_id == user_id, Resume.idempotency_key == idempotency_key
        )
    )
    return result.scalar_one_or_none()


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
    """
    # ── 幂等短路：同 key 已存在 → 返回已有记录 ──
    if idempotency_key:
        existing = await _find_resume_by_idempotency_key(db, current_user.id, idempotency_key)
        if existing is not None:
            response.status_code = 200
            return UploadAsyncResponse(
                id=existing.id,
                filename=existing.filename,
                status=existing.status,
            )

    file_path, filename = await resume_service.save_upload_file(file)
    resume = await resume_service.create_resume_quick(
        db, current_user.id, filename, file_path
    )
    # 把幂等键落库，供后续同 key 请求命中
    if idempotency_key:
        resume.idempotency_key = idempotency_key
        await db.commit()
        await db.refresh(resume)

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
    limit: int = 20,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """分页查当前用户的简历列表。"""
    items, total = await resume_service.get_user_resumes(
        db, current_user.id, limit, offset
    )
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
