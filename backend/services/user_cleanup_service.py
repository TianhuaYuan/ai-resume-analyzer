"""用户账户删除服务：级联清理用户所有数据。

S1-T8: 删除账户时清理物理文件 + ChromaDB 集合 + DB 记录。
DB 层外键已配置 ondelete=CASCADE（resumes/qa_history/job_applications），
但物理文件、向量库、Redis 缓存、内存缓存需要手动清理。

清理清单（对齐现行命名，杜绝孤儿数据）：
1. Chroma ``knowledge_{user_id}``：该用户全部简历/资产向量
   （现行每用户一个集合，非旧 ``resume_{rid}`` 命名——旧命名删不到任何集合）
2. Chroma ``memory_{user_id}``：L4 长期语义记忆
3. Redis ``resume_analysis:{rid}:{type}``：每份简历 4 种分析缓存
4. Embedding 内存缓存（按 resume_id 追踪）
5. BM25 内存索引（clear_user_bm25 清全部 scope 组合 key）
6. 物理上传文件
7. DB 用户行（外键级联清关联记录）
"""

import logging
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core import cache as embedding_cache
from core.config import settings
from models.resume import Resume
from models.user import User
from services.rag.clients import knowledge_collection_name
from services.rag.retrieval import clear_user_bm25
from services.resume_analysis_cache import invalidate_resume_cache
from services.vector_store import get_vector_store

logger = logging.getLogger(__name__)


async def delete_user_account(db: AsyncSession, user: User) -> None:
    """删除用户账户及所有关联数据（外部资源先行，DB 删除最后）。

    清理顺序：
    1. 删 Chroma knowledge_{user_id} + memory_{user_id} 集合（集合不存在由 adapter 忽略）
    2. 逐简历清 Redis 分析缓存 + Embedding 内存缓存
    3. 清 BM25 内存索引
    4. 删物理文件
    5. 删用户（DB 外键级联删 resumes/qa_history/job_applications 等）
    """
    user_id = user.id

    # 1. 查询所有简历（拿 id + 文件路径）
    result = await db.execute(select(Resume).where(Resume.user_id == user_id))
    resumes = result.scalars().all()

    file_paths = [r.file_path for r in resumes if r.file_path]
    resume_ids = [r.id for r in resumes]

    # 2. 删向量集合（集合不存在由 adapter 吞掉 ValueError；真实连接错误向上传播）
    for collection_name in (knowledge_collection_name(user_id), f"memory_{user_id}"):
        try:
            await get_vector_store().delete_collection(collection_name)
            logger.info("Deleted ChromaDB collection: %s", collection_name)
        except Exception:
            logger.warning("ChromaDB cleanup skipped for %s", collection_name, exc_info=True)

    # 3. 逐简历清 Redis 分析缓存 + Embedding 内存缓存
    #    invalidate_resume_cache 内部已吞异常（best-effort）；embedding_cache 为纯内存不抛
    for rid in resume_ids:
        await invalidate_resume_cache(rid)
        await embedding_cache.clear_resume(rid)

    # 4. 清 BM25 内存索引（该用户全部 scope 组合 key）
    await clear_user_bm25(user_id)

    # 5. 删物理文件
    for fp in file_paths:
        try:
            path = Path(fp)
            if path.exists():
                path.unlink()
                logger.info("Deleted resume file: %s", fp)
        except Exception:
            logger.warning("Failed to delete file: %s", fp, exc_info=True)

    # 5.5 删头像文件（basic_info 模块 content.avatar，uploads/avatars/）
    #     DB 级联只删记录不删磁盘文件，否则头像成为孤儿文件
    if resumes:
        from services.avatar_service import delete_avatar
        from services.resume_builder import get_resume_with_modules

        for r in resumes:
            try:
                _, mods = await get_resume_with_modules(db, user_id, r.id)
                for m in mods or []:
                    if (
                        m.module_type == "basic_info"
                        and isinstance(m.content, dict)
                        and m.content.get("avatar")
                    ):
                        delete_avatar(str(m.content["avatar"]))
            except Exception:
                logger.warning(
                    "Failed to clean avatar for resume %s", r.id, exc_info=True
                )

    # 6. 删用户（DB 级联删除关联记录）
    await db.delete(user)
    await db.commit()
    logger.info("User account deleted: user_id=%s", user_id)
