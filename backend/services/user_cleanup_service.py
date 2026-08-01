"""用户账户删除服务：级联清理用户所有数据。

S1-T8: 删除账户时清理物理文件 + ChromaDB 集合 + DB 记录。
DB 层外键已配置 ondelete=CASCADE（resumes/qa_history/job_applications），
但物理文件和向量库需要手动清理。
"""

import logging
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from models.resume import Resume
from models.user import User

logger = logging.getLogger(__name__)


async def delete_user_account(db: AsyncSession, user: User) -> None:
    """删除用户账户及所有关联数据。

    清理顺序：
    1. 查询用户所有简历文件路径
    2. 删除 ChromaDB 集合（按 resume_id 命名）
    3. 删除物理文件
    4. 删除用户（DB 外键级联删除 resumes/qa_history/job_applications）
    """
    user_id = user.id

    # 1. 查询所有简历文件路径
    result = await db.execute(select(Resume).where(Resume.user_id == user_id))
    resumes = result.scalars().all()

    file_paths = [r.file_path for r in resumes if r.file_path]
    resume_ids = [r.id for r in resumes]

    # 2. 删除 ChromaDB 集合
    for rid in resume_ids:
        try:
            from services.rag.clients import get_chroma_client

            chroma = get_chroma_client()
            collection_name = f"resume_{rid}"
            try:
                chroma.delete_collection(collection_name)
                logger.info("Deleted ChromaDB collection: %s", collection_name)
            except Exception:
                # 集合可能不存在，忽略
                pass
        except Exception:
            logger.warning("ChromaDB cleanup skipped for resume_%s", rid, exc_info=True)

    # 3. 删除物理文件
    for fp in file_paths:
        try:
            path = Path(fp)
            if path.exists():
                path.unlink()
                logger.info("Deleted resume file: %s", fp)
        except Exception:
            logger.warning("Failed to delete file: %s", fp, exc_info=True)

    # 4. 删除用户（DB 级联删除关联记录）
    await db.delete(user)
    await db.commit()
    logger.info("User account deleted: user_id=%s", user_id)
