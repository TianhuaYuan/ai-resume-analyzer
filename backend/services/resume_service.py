import logging
import os
import uuid
from pathlib import Path

from fastapi import HTTPException, UploadFile, status
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from core import cache as embedding_cache
from core.config import settings
from core.database import AsyncSessionLocal
from models.resume import Resume
from services.rag.pipeline import clear_resume_vectors, process_resume
from utils.file_parser import parse_resume

logger = logging.getLogger(__name__)


UPLOAD_DIR = Path(settings.UPLOAD_DIR).resolve()
UPLOAD_DIR.mkdir(exist_ok=True)


ALLOWED_EXTENSIONS = {".pdf", ".docx", ".txt"}
ALLOWED_MIME_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "text/plain",
}
CHUNK_SIZE = 64 * 1024  # 64KB per read chunk


async def save_upload_file(file: UploadFile) -> tuple[str, str]:
    """将上传文件保存到 uploads/，返回 (存储路径, 原始文件名)。
    Content-Length 预检 → 扩展名/MIME 白名单 → 流式写入 + 实时大小检查。"""
    original = file.filename or "resume.bin"
    ext = Path(original).suffix.lower()

    # 1. 扩展名白名单
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"不支持的文件类型 {ext}，仅允许 {', '.join(ALLOWED_EXTENSIONS)}",
        )

    # 2. MIME 类型白名单
    if file.content_type and file.content_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"不支持的 MIME 类型 {file.content_type}",
        )

    # 3. Content-Length 预检（快速拒绝超大文件）
    max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    if file.size and file.size > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"文件大小 {file.size / (1024 * 1024):.1f}MB 超过限制 {settings.MAX_UPLOAD_SIZE_MB}MB",
        )

    # 4. 流式写入 + 实时大小检查
    unique_name = f"{uuid.uuid4().hex}{ext}"
    save_path = UPLOAD_DIR / unique_name
    written = 0

    with open(save_path, "wb") as f:
        while chunk := await file.read(CHUNK_SIZE):
            written += len(chunk)
            if written > max_bytes:
                f.close()
                save_path.unlink(missing_ok=True)
                raise HTTPException(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    detail=f"文件大小超过限制 {settings.MAX_UPLOAD_SIZE_MB}MB",
                )
            f.write(chunk)

    return str(save_path), original


async def create_resume_quick(
    db: AsyncSession,
    user_id: int,
    filename: str,
    file_path: str,
    idempotency_key: str | None = None,
) -> Resume:
    """快速创建 resume 行（status=processing），不阻塞等 RAG 处理。

    P1-9: idempotency_key 与基本信息在一次 commit 内写入，触发 DB 层 UNIQUE 约束
    兜底并发竞态——应用层短路检查 + DB 唯一约束双重防御。

    Raises:
        IntegrityError: (user_id, idempotency_key) 撞 UNIQUE 约束时抛出，
                        调用方应 rollback 后查询已有记录返回。
    """
    resume = Resume(
        user_id=user_id,
        filename=filename,
        file_path=file_path,
        parsed_text="",
        chunk_count=0,
        status="processing",
        idempotency_key=idempotency_key,
    )
    db.add(resume)
    await db.commit()
    await db.refresh(resume)
    return resume


async def recover_stuck_resumes() -> int:
    """P1-13：启动时恢复卡住的简历。

    进程崩溃/重启后，status=processing 的简历后台任务已丢失，
    永远不会完成。启动时把它们标记为 failed，让用户可以手动重试。

    Returns:
        被恢复的简历数量
    """
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Resume).where(Resume.status == "processing")
        )
        stuck = result.scalars().all()
        if not stuck:
            return 0
        for resume in stuck:
            resume.status = "failed"
            resume.status_message = "处理异常中断，请重试"
        await db.commit()
        logger.warning("Recovered %d stuck resumes (processing → failed)", len(stuck))
        return len(stuck)


async def retry_resume_processing(
    db: AsyncSession, resume_id: int, user_id: int
) -> Resume:
    """P1-24：手动重试失败的简历处理。

    Args:
        db: 数据库 session
        resume_id: 简历 ID
        user_id: 当前用户 ID

    Returns:
        更新后的 Resume 对象（status=processing）

    Raises:
        HTTPException 404: 简历不存在或不属于该用户
        HTTPException 409: 简历状态不是 failed
    """
    resume = await get_resume(db, resume_id, user_id)
    if resume.status != "failed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"仅失败简历可重试（当前状态: {resume.status}）",
        )
    resume.status = "processing"
    resume.status_message = ""
    await db.commit()
    await db.refresh(resume)
    return resume


async def process_resume_background(resume_id: int, file_path: str):
    """后台任务：解析文件 → 分块 → 向量化 → 更新状态。
    用独立的 DB session，因为原请求 session 已关闭。"""
    async with AsyncSessionLocal() as db:
        try:
            parsed_text = parse_resume(file_path)
            chunk_count = await process_resume(resume_id, parsed_text)
            await db.execute(
                update(Resume)
                .where(Resume.id == resume_id)
                .values(parsed_text=parsed_text, chunk_count=chunk_count, status="ready")
            )
            await db.commit()
        except Exception:
            # P1-10：logger.exception 保留完整 traceback，便于定位根因
            logger.exception("Background processing failed for resume %d", resume_id)
            # P1-10：先 rollback 清理 session 脏状态，否则二次 commit 可能连带失败
            await db.rollback()
            try:
                await db.execute(
                    update(Resume)
                    .where(Resume.id == resume_id)
                    .values(status="failed", status_message="处理失败，请重新上传")
                )
                await db.commit()
            except Exception:
                # P1-10：二次 commit 也可能失败（如 DB 连接断开），不能静默吞掉
                logger.exception(
                    "Failed to mark resume %d as failed (commit error)", resume_id
                )


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
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="简历不存在")
    return resume


async def delete_resume(db: AsyncSession, resume_id: int, user_id: int) -> None:
    """先清外部资源（Chroma/文件/缓存）→ 最后删 MySQL（CASCADE 清历史）。

    P2-4 修正：原顺序「先删 DB 再清外部资源」，若 DB commit 后外部清理失败，
    会产生孤儿（DB 没了但 Chroma/文件还在，无法重试）。改为先清外部资源，
    DB 删除放最后——外部清理失败时 DB 仍保留，用户可重试删除。
    """
    resume = await get_resume(db, resume_id, user_id)
    file_path = resume.file_path

    # 1. 清 ChromaDB 向量 + BM25 内存索引（内部已吞 Chroma 异常，仅 warning + 重连）
    await clear_resume_vectors(resume_id)
    # 2. 清 Embedding 内存缓存
    cleared = await embedding_cache.clear_resume(resume_id)
    logger.info("Cleared %d embedding cache entries for resume %d", cleared, resume_id)
    # 3. 删上传的原始文件（文件丢失仅 warning，不影响 DB 删除）
    try:
        os.remove(file_path)
    except Exception:
        logger.warning("Failed to delete resume file: %s", file_path)
    # 4. 最后删 MySQL（CASCADE 自动清理 qa_history 等关联记录）
    await db.delete(resume)
    await db.commit()
