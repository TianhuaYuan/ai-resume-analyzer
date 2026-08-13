"""简历清理服务 — 级联删除、孤儿扫描、stale processing 清扫。

设计原则（spec A6）：DB-first + 外部尽力清理 + 孤儿扫描兜底。
- delete_resume_full: 先删 DB（事务），再尽力清外部资源（Chroma/缓存/磁盘）
- cleanup_stale_processing: 定时清扫卡住超过 30min 的 processing 简历
- orphan_scan: 扫描没有 DB 记录的孤儿文件和 Chroma collection
"""

import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core import cache as embedding_cache
from core.config import settings
from core.database import AsyncSessionLocal
from models.resume import Resume
from models.user import User
from services.rag.clients import get_chroma_client
from services.rag.pipeline import clear_resume_vectors

logger = logging.getLogger(__name__)

UPLOAD_DIR = Path(settings.UPLOAD_DIR).resolve()

# stale processing 超时阈值
STALE_PROCESSING_MINUTES = 30


async def delete_resume_full(db: AsyncSession, resume: Resume) -> None:
    """DB 事务先行 → 外部资源尽力清理 → 日志记录。

    与 resume_service.delete_resume 的区别：
    - delete_resume: 先清外部再删 DB（外部失败可重试删除）
    - delete_resume_full: 先删 DB 再清外部（用于确定要删的场景，如用户确认删账户）

    外部资源清理失败不抛异常，仅记录 warning，避免阻塞主流程。

    保留待账户删除功能落地时接入；当前 DELETE 端点不替换（保持 P2-4 外部-first 顺序）。
    """
    resume_id = resume.id
    user_id = resume.user_id
    file_path = resume.file_path

    # 1. DB 事务先行
    await db.delete(resume)
    await db.commit()
    logger.info("Resume %d deleted from DB", resume_id)

    # 2. 清 ChromaDB 向量（尽力，不阻塞）
    try:
        await clear_resume_vectors(user_id, resume_id)
        logger.info("Cleared Chroma vectors for resume %d", resume_id)
    except Exception as e:
        logger.warning("Failed to clear Chroma vectors for resume %d: %s", resume_id, e)

    # 3. 清 Embedding 内存缓存
    try:
        cleared = await embedding_cache.clear_resume(resume_id)
        logger.info("Cleared %d embedding cache entries for resume %d", cleared, resume_id)
    except Exception as e:
        logger.warning("Failed to clear embedding cache for resume %d: %s", resume_id, e)

    # 4. 删上传文件
    if file_path and os.path.exists(file_path):
        try:
            os.remove(file_path)
            logger.info("Deleted resume file: %s", file_path)
        except Exception as e:
            logger.warning("Failed to delete resume file %s: %s", file_path, e)


async def cleanup_stale_processing() -> int:
    """清扫创建时间超过 30min 的 processing 简历。

    Returns:
        被清扫的简历数量
    """
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=STALE_PROCESSING_MINUTES)

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Resume).where(
                Resume.status == "processing",
                Resume.created_at < cutoff,
            )
        )
        stale_resumes = result.scalars().all()
        if not stale_resumes:
            return 0

        for resume in stale_resumes:
            from services.resume_service import set_resume_status

            await set_resume_status(
                db,
                resume,
                "failed",
                reason=f"处理超时（>{STALE_PROCESSING_MINUTES}分钟未完成的自动标记为失败，请重试）",
            )
            logger.warning(
                "Stale processing resume %d marked as failed (created_at=%s)",
                resume.id,
                resume.created_at,
            )

        await db.commit()
        return len(stale_resumes)


async def orphan_scan() -> dict[str, list[str]]:
    """扫描孤儿文件和 Chroma collection。

    Returns:
        {"files": [...], "chromadb": [...]}
    """
    orphans: dict[str, list[str]] = {"files": [], "chromadb": []}

    async with AsyncSessionLocal() as db:
        # 获取所有 resume 的文件路径
        result = await db.execute(select(Resume.file_path))
        db_files = {row[0] for row in result.all() if row[0]}
        # 只取文件名部分用于比对
        db_file_names = {Path(f).name for f in db_files}

        # 获取所有 resume ID
        result = await db.execute(select(Resume.id))
        db_resume_ids = {row[0] for row in result.all()}

        # 获取所有用户 ID（knowledge_{user_id} 集合按"用户是否存在"判定孤儿）
        result = await db.execute(select(User.id))
        db_user_ids = {row[0] for row in result.all()}

        # 收集所有被引用的头像文件名（basic_info 模块 content.avatar）
        # 头像 UUID 文件名无用户关联，只能按「是否被任何简历引用」判定孤儿
        from models.resume_module import ResumeModule

        referenced_avatars: set[str] = set()
        try:
            result = await db.execute(
                select(ResumeModule.content).where(
                    ResumeModule.module_type == "basic_info"
                )
            )
            for (content,) in result.all():
                if isinstance(content, dict) and content.get("avatar"):
                    referenced_avatars.add(Path(str(content["avatar"])).name)
        except Exception as e:
            # Avatar references are an optional cleanup hint.  A partial/legacy
            # database must not prevent scanning resume files and collections.
            logger.warning("Failed to scan referenced avatars: %s", e)

    # 1. 扫描磁盘孤儿文件（uploads/ 根目录 + uploads/avatars/ 子目录）
    if UPLOAD_DIR.exists():
        try:
            for entry in os.listdir(UPLOAD_DIR):
                full_path = UPLOAD_DIR / entry
                if full_path.is_file() and entry not in db_file_names:
                    orphans["files"].append(entry)
            # avatars 子目录：未被任何简历 basic_info.avatar 引用的文件为孤儿
            avatars_dir = UPLOAD_DIR / "avatars"
            # Keep the optional avatar scan conservative: a mocked/custom
            # upload root must not make an arbitrary child look like a real
            # directory, while the production Path implementation is scanned.
            if isinstance(avatars_dir, Path) and avatars_dir.is_dir():
                for entry in os.listdir(avatars_dir):
                    full_path = avatars_dir / entry
                    if full_path.is_file() and entry not in referenced_avatars:
                        # 用相对路径标识，auto_cleanup 按目录删除
                        orphans["files"].append(f"avatars/{entry}")
        except Exception as e:
            logger.warning("Failed to scan upload directory: %s", e)

    # 2. 扫描 Chroma 孤儿 collection
    try:
        client = get_chroma_client()
        collections = client.list_collections()
        for coll in collections:
            # list_collections 可能返回 Collection 对象或字符串
            coll_name = getattr(coll, "name", coll)
            if not isinstance(coll_name, str):
                continue
            # 旧遗留命名：resume_<id>（按简历 id 是否存在判定）
            if coll_name.startswith("resume_"):
                try:
                    resume_id = int(coll_name.split("_", 1)[1])
                    if resume_id not in db_resume_ids:
                        orphans["chromadb"].append(coll_name)
                except (ValueError, IndexError):
                    orphans["chromadb"].append(coll_name)
            # 现行命名：knowledge_{user_id}（按用户 id 是否存在判定）
            elif coll_name.startswith("knowledge_"):
                try:
                    uid = int(coll_name.split("_", 1)[1])
                    if uid not in db_user_ids:
                        orphans["chromadb"].append(coll_name)
                except (ValueError, IndexError):
                    orphans["chromadb"].append(coll_name)
            # L4 长期记忆集合：memory_{user_id}（账户删除/用户不存在时会残留，按用户 id 判定）
            elif coll_name.startswith("memory_"):
                try:
                    uid = int(coll_name.split("_", 1)[1])
                    if uid not in db_user_ids:
                        orphans["chromadb"].append(coll_name)
                except (ValueError, IndexError):
                    orphans["chromadb"].append(coll_name)
    except Exception as e:
        logger.warning("Failed to scan Chroma collections: %s", e)

    if orphans["files"] or orphans["chromadb"]:
        logger.info(
            "Orphan scan found %d files, %d chromadb collections",
            len(orphans["files"]),
            len(orphans["chromadb"]),
        )

    return orphans


async def auto_cleanup_orphans(dry_run: bool = False) -> dict:
    """自动清理孤儿文件和 ChromaDB 集合。

    Args:
        dry_run: True 时只报告不删除（默认 False）

    Returns:
        清理结果报告
    """
    orphans = await orphan_scan()

    report = {
        "disk_deleted": 0,
        "disk_failed": 0,
        "chroma_deleted": 0,
        "chroma_failed": 0,
        "errors": [],
    }

    # 1. 清理磁盘孤儿文件
    for filename in orphans["files"]:
        if dry_run:
            report["disk_deleted"] += 1
            continue
        file_path = UPLOAD_DIR / filename
        try:
            os.remove(file_path)
            report["disk_deleted"] += 1
            logger.info("Auto-deleted orphan file: %s", filename)
        except Exception as e:
            report["disk_failed"] += 1
            report["errors"].append(f"Failed to delete {filename}: {e}")
            logger.warning("Failed to auto-delete orphan file %s: %s", filename, e)

    # 2. 清理 ChromaDB 孤儿集合
    for collection_name in orphans["chromadb"]:
        if dry_run:
            report["chroma_deleted"] += 1
            continue
        try:
            from services.rag.clients import with_chroma

            def _delete(name=collection_name):
                client = get_chroma_client()
                client.delete_collection(name)

            await with_chroma(_delete)
            report["chroma_deleted"] += 1
            logger.info("Auto-deleted orphan Chroma collection: %s", collection_name)
        except Exception as e:
            report["chroma_failed"] += 1
            report["errors"].append(f"Failed to delete Chroma collection {collection_name}: {e}")
            logger.warning("Failed to auto-delete Chroma collection %s: %s", collection_name, e)

    return report


# ── 过期简历清理 ──


async def cleanup_expired_resumes() -> int:
    """清理已过期的简历。

    清理逻辑：
    1. 查找 expires_at < now() 且 status != 'expired' 的简历
    2. 对每个过期简历：清理外部资源 → 标记为 expired

    Returns:
        清理的简历数量
    """
    now = datetime.now(timezone.utc)

    async with AsyncSessionLocal() as db:
        # 查找已过期但未标记为 expired 的简历
        result = await db.execute(
            select(Resume.id, Resume.file_path, Resume.user_id).where(
                Resume.expires_at < now,
                Resume.status != "expired",
            )
        )
        expired_resumes = result.all()

        if not expired_resumes:
            return 0

        logger.info("Found %d expired resumes to cleanup", len(expired_resumes))

        cleaned_count = 0
        for resume_id, file_path, user_id in expired_resumes:
            try:
                # 1. 清理 ChromaDB 向量
                try:
                    from services.rag.clients import with_chroma, knowledge_collection_name

                    async def _clear_vectors():
                        client = get_chroma_client()
                        collection_name = knowledge_collection_name(user_id)
                        try:
                            collection = client.get_collection(collection_name)
                            collection.delete(where={"asset_id": str(resume_id)})
                        except Exception:
                            pass  # 集合不存在或其他错误，忽略

                    await with_chroma(_clear_vectors)
                except Exception as e:
                    logger.warning("Failed to clear vectors for expired resume %d: %s", resume_id, e)

                # 2. 清理 Embedding 内存缓存
                try:
                    from core.cache import embedding_cache

                    embedding_cache.clear_resume(resume_id)
                except Exception as e:
                    logger.warning("Failed to clear embedding cache for expired resume %d: %s", resume_id, e)

                # 3. 清理 BM25 内存索引
                try:
                    from services.rag.retrieval import clear_bm25

                    clear_bm25(user_id, resume_id)
                except Exception as e:
                    logger.warning("Failed to clear BM25 index for expired resume %d: %s", resume_id, e)

                # 4. 删除物理文件
                if file_path:
                    try:
                        file = Path(file_path)
                        if file.exists():
                            file.unlink()
                            logger.info("Deleted expired resume file: %s", file_path)
                    except Exception as e:
                        logger.warning("Failed to delete expired resume file %s: %s", file_path, e)

                # 5. 标记为 expired
                resume_result = await db.execute(select(Resume).where(Resume.id == resume_id))
                resume = resume_result.scalar_one_or_none()
                if resume:
                    from services.resume_service import set_resume_status

                    await set_resume_status(
                        db,
                        resume,
                        "expired",
                        reason=f"简历已过期（过期时间: {resume.expires_at}）",
                    )
                    resume.status_message = f"简历已过期（过期时间: {resume.expires_at}）"

                cleaned_count += 1
                logger.info("Cleaned up expired resume: id=%d", resume_id)

            except Exception as e:
                logger.error("Failed to cleanup expired resume %d: %s", resume_id, e)

        await db.commit()

        if cleaned_count > 0:
            logger.info("Successfully cleaned up %d expired resumes", cleaned_count)

        return cleaned_count
