from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_current_user
from core.database import get_db
from models.user import User
from schemas.resume import ResumeListResponse, ResumeResponse, UploadResponse
from services import resume_service

router = APIRouter(prefix="/api/resumes", tags=["resumes"])


@router.post("", response_model=UploadResponse, status_code=201)
async def upload_resume(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """上传简历。解析文件 → 分块 → 向量化 → Chroma 入库。"""
    file_path, filename = await resume_service.save_upload_file(file)
    resume = await resume_service.create_resume(
        db, current_user.id, filename, file_path
    )
    return UploadResponse(
        id=resume.id,
        filename=resume.filename,
        preview=resume.parsed_text[:200],
        chunk_count=resume.chunk_count,
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
    """查单份简历。非本人→404。"""
    return await resume_service.get_resume(db, resume_id, current_user.id)


@router.delete("/{resume_id}", status_code=204)
async def delete_resume(
    resume_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """删简历。先删 MySQL（CASCADE 清历史）→ 清 Chroma → 删文件。"""
    await resume_service.delete_resume(db, resume_id, current_user.id)
    return None
