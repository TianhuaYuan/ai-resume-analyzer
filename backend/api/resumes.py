from fastapi import APIRouter, BackgroundTasks, Depends, File, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_current_user
from core.database import get_db
from models.user import User
from schemas.resume import ResumeListResponse, ResumeResponse, UploadAsyncResponse
from services import resume_service

router = APIRouter(prefix="/api/resumes", tags=["resumes"])


@router.post("", response_model=UploadAsyncResponse, status_code=202)
async def upload_resume(
    file: UploadFile = File(...),
    background: BackgroundTasks = None,  # type: ignore[assignment]
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """上传简历。立即返回 202，后台异步解析+分块+向量化。"""
    file_path, filename = await resume_service.save_upload_file(file)
    resume = await resume_service.create_resume_quick(
        db, current_user.id, filename, file_path
    )
    background.add_task(resume_service.process_resume_background, resume.id, file_path)
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
