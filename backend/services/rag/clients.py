"""外部客户端单例（Chat / Embedding / Chroma）与 Chroma 簿记。

阶段11 从 rag_service.py 拆出：这些是与"外部服务连接"相关的全局状态与工厂，
独立于检索/分块/编排逻辑，单独成模块便于单测与复用。
"""

import asyncio
import logging
import os
import shutil
import sqlite3

import chromadb
from openai import AsyncOpenAI

from core.config import settings

logger = logging.getLogger(__name__)

# 全局 Chroma 操作锁：PersistentClient 非线程安全，并发写（delete/create/add）
# 与并发读（query/get）会损坏 HNSW 索引文件（Bug 3）。
# 所有 Chroma 操作必须通过 with_chroma 串行化。
_chroma_lock = asyncio.Lock()


async def with_chroma(func, *args, **kwargs):
    """在全局锁保护下 + 线程隔离中执行 Chroma 操作。

    PersistentClient 内部使用 SQLite + HNSW 文件，非线程安全。
    多个 asyncio Task 通过 asyncio.to_thread 并发访问同一 client 会导致
    ``InternalError: Error creating hnsw segment reader: Nothing found on disk``。

    本函数确保所有 Chroma 操作（读/写）串行执行，彻底消除并发损坏。
    """
    async with _chroma_lock:
        return await asyncio.to_thread(func, *args, **kwargs)


# 单次调用超时（秒）：Embedding/LLM 为网络上游，必须设超时以防无限挂起（阶段1 加固）
_CHAT_TIMEOUT = 60.0
_EMBEDDING_TIMEOUT = 30.0

_chat_client: AsyncOpenAI | None = None
_judge_client: AsyncOpenAI | None = None
_embedding_client: AsyncOpenAI | None = None
_chroma_client = None


def get_chat_client() -> AsyncOpenAI:
    global _chat_client
    if _chat_client is None:
        _chat_client = AsyncOpenAI(
            api_key=settings.CHAT_API_KEY,
            base_url=settings.CHAT_BASE_URL,
            timeout=_CHAT_TIMEOUT,
        )
    return _chat_client


def get_judge_client() -> AsyncOpenAI:
    """T10: JUDGE_MODEL 客户端（中间轮快速推理用，独立 API key/base_url）。"""
    global _judge_client
    if _judge_client is None:
        _judge_client = AsyncOpenAI(
            api_key=settings.JUDGE_API_KEY or settings.CHAT_API_KEY,
            base_url=settings.JUDGE_BASE_URL,
            timeout=_CHAT_TIMEOUT,
        )
    return _judge_client


def get_embedding_client() -> AsyncOpenAI:
    global _embedding_client
    if _embedding_client is None:
        _embedding_client = AsyncOpenAI(
            api_key=settings.EMBEDDING_API_KEY,
            base_url=settings.EMBEDDING_BASE_URL,
            timeout=_EMBEDDING_TIMEOUT,
        )
    return _embedding_client


def get_chroma_client():
    global _chroma_client
    if _chroma_client is None:
        _chroma_client = _create_chroma_client()
    return _chroma_client


def _create_chroma_client():
    return chromadb.PersistentClient(path=settings.CHROMA_PERSIST_DIR)


def reconnect_chroma():
    """ChromaDB 连接失效时重建客户端（N2：重连）。"""
    global _chroma_client
    _chroma_client = _create_chroma_client()
    return _chroma_client


def _collection_name(resume_id: int) -> str:
    return f"resume_{resume_id}"


def _cleanup_orphan_segments() -> int:
    """清理 ChromaDB delete_collection 在 Windows 上留下的孤儿 HNSW 目录"""
    persist_dir = settings.CHROMA_PERSIST_DIR
    if not os.path.isdir(persist_dir):
        return 0

    # 从磁盘收集所有 UUID 格式的目录
    disk_dirs = set()
    for entry in os.listdir(persist_dir):
        full = os.path.join(persist_dir, entry)
        if os.path.isdir(full) and len(entry) == 36 and entry.count("-") == 4:
            disk_dirs.add(entry)

    if not disk_dirs:
        return 0

    # 从 SQLite 查活跃 segment ID
    try:
        # ChromaDB 不暴露 segments 列表，直接从 SQLite 读
        db_path = os.path.join(persist_dir, "chroma.sqlite3")
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute("SELECT id FROM segments")
        active = {row[0] for row in cur.fetchall()}
        conn.close()
    except Exception:
        return 0

    orphans = disk_dirs - active
    for d in orphans:
        shutil.rmtree(os.path.join(persist_dir, d), ignore_errors=True)
        logger.info("Removed orphan ChromaDB segment: %s", d)

    return len(orphans)
