import logging
import os
import uuid
from pathlib import Path

from fastapi import HTTPException, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from models.resume import Resume
from services import rag_service
from utils.file_parser import parse_resume

logger = logging.getLogger(__name__)


UPLOAD_DIR = Path(settings.UPLOAD_DIR).resolve()
UPLOAD_DIR.mkdir(exist_ok=True)


async def save_upload_file(file: UploadFile) -> tuple[str, str]:
    """将上传文件保存到 uploads/，返回 (存储路径, 原始文件名)"""
    original = file.filename or "resume.bin"
    ext = Path(original).suffix
    unique_name = f"{uuid.uuid4().hex}{ext}"
    save_path = UPLOAD_DIR / unique_name
    content = await file.read()
    with open(save_path, "wb") as f:
        f.write(content)
    return str(save_path), original


async def create_resume(db: AsyncSession, user_id: int, filename: str, file_path: str) -> Resume:
    """解析文件 → 存入 MySQL → 切块入 Chroma → 更新 chunk_count"""
    parsed_text = parse_resume(file_path)
    resume = Resume(
        user_id=user_id,
        filename=filename,
        file_path=file_path,
        parsed_text=parsed_text,
        chunk_count=0,
    )
    db.add(resume)
    await db.commit()
    await db.refresh(resume)

    chunk_count = await rag_service.process_resume(resume.id, parsed_text)
    resume.chunk_count = chunk_count
    await db.commit()
    return resume


async def get_user_resumes(
    db: AsyncSession, user_id: int, limit: int = 20, offset: int = 0
) -> tuple[list[Resume], int]:
    """分页查用户简历列表"""
    total_result = await db.execute(
        select(func.count()).select_from(Resume).where(Resume.user_id == user_id)
    )
    total = total_result.scalar_one()
    result = await db.execute(
        select(Resume)
        .where(Resume.user_id == user_id)
        .order_by(Resume.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return result.scalars().all(), total


async def get_resume(db: AsyncSession, resume_id: int, user_id: int) -> Resume:
    """查单份简历，校验归属。不存在→404"""
    result = await db.execute(
        select(Resume).where(Resume.id == resume_id, Resume.user_id == user_id)
    )
    resume = result.scalar_one_or_none()
    if resume is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="简历不存在"
        )
    return resume


async def delete_resume(db: AsyncSession, resume_id: int, user_id: int) -> None:
    """先删 MySQL（CASCADE 清历史）→ 清 Chroma → 删文件"""
    resume = await get_resume(db, resume_id, user_id)
    file_path = resume.file_path
    await db.delete(resume)
    await db.commit()

    rag_service.clear_resume_vectors(resume_id)
    try:
        os.remove(file_path)
    except Exception:
        logger.warning("Failed to delete resume file: %s", file_path)
