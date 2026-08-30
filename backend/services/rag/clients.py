"""外部客户端单例（Chat / Embedding / Chroma）与 Chroma 簿记。

阶段11 从 rag_service.py 拆出：这些是与"外部服务连接"相关的全局状态与工厂，
独立于检索/分块/编排逻辑，单独成模块便于单测与复用。
"""

import asyncio
import logging
import os
import shutil
import sqlite3
from dataclasses import dataclass

import chromadb
from openai import AsyncOpenAI

from core.config import settings
from core.circuit_breaker import CircuitBreaker

logger = logging.getLogger(__name__)

# 全局 Chroma 操作锁：PersistentClient 非线程安全，并发写（delete/create/add）
# 与并发读（query/get）会损坏 HNSW 索引文件（Bug 3）。
# 所有 Chroma 操作必须通过 with_chroma 串行化。
_chroma_lock = asyncio.Lock()

# 熔断器：按外部依赖独立实例化。
# - chat 熔断：Chat 主模型 + 传统 RAG 生成共用（同一上游 API）
# - judge 熔断：JUDGE_MODEL 快速推理独立上游（独立 key/base_url）
# 连续失败阈值/recovery 来自 settings（缺省 5 次/30s，与 circuit_breaker 默认一致）。
_breaker_failure_threshold = int(getattr(settings, "LLM_BREAKER_FAILURE_THRESHOLD", 5))
_breaker_recovery_timeout = float(getattr(settings, "LLM_BREAKER_RECOVERY_SECONDS", 30))
_chat_breaker: CircuitBreaker | None = None
_judge_breaker: CircuitBreaker | None = None


def get_chat_breaker() -> CircuitBreaker | None:
    """Chat 上游熔断器（单例）。外部依赖故障时快速失败，不重复打上游。"""
    global _chat_breaker
    if _chat_breaker is None:
        _chat_breaker = CircuitBreaker(
            name="chat_llm",
            failure_threshold=_breaker_failure_threshold,
            recovery_timeout=_breaker_recovery_timeout,
        )
    return _chat_breaker


def get_judge_breaker() -> CircuitBreaker | None:
    """Judge 上游熔断器（单例）。"""
    global _judge_breaker
    if _judge_breaker is None:
        _judge_breaker = CircuitBreaker(
            name="judge_llm",
            failure_threshold=_breaker_failure_threshold,
            recovery_timeout=_breaker_recovery_timeout,
        )
    return _judge_breaker


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
_fallback_clients: dict[str, AsyncOpenAI] = {}


@dataclass(frozen=True)
class FallbackProvider:
    name: str
    api_key: str
    base_url: str
    model: str
    input_cost_cny: float = 0.0
    output_cost_cny: float = 0.0


def get_fallback_providers() -> list[FallbackProvider]:
    """读取最多 3 个独立 provider；未填完整 key/url/model 的组跳过。"""
    providers: list[FallbackProvider] = []
    for index in range(1, 2):
        prefix = f"CHAT_FALLBACK_{index}_"
        api_key = (getattr(settings, prefix + "API_KEY", "") or "").strip()
        base_url = (getattr(settings, prefix + "BASE_URL", "") or "").strip()
        model = (getattr(settings, prefix + "MODEL", "") or "").strip()
        if not (api_key and base_url and model):
            continue
        providers.append(FallbackProvider(
            name=f"fallback-{index}", api_key=api_key, base_url=base_url,
            model=model,
            input_cost_cny=float(getattr(settings, prefix + "INPUT_COST_PER_MILLION_CNY", 0.0)),
            output_cost_cny=float(getattr(settings, prefix + "OUTPUT_COST_PER_MILLION_CNY", 0.0)),
        ))
    return providers


def get_fallback_client(provider: FallbackProvider) -> AsyncOpenAI:
    """按 provider 配置缓存独立 AsyncOpenAI client。"""
    client = _fallback_clients.get(provider.name)
    if client is None:
        client = AsyncOpenAI(api_key=provider.api_key, base_url=provider.base_url, timeout=_CHAT_TIMEOUT)
        _fallback_clients[provider.name] = client
    return client


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


def knowledge_collection_name(user_id: int) -> str:
    """每用户知识资产集合名。

    一个用户的所有资产（resume/jd/interview/note）共用一个集合，
    内部按 metadata（asset_id/version/is_latest）过滤，支持跨资产单查询。
    """
    return f"knowledge_{user_id}"


# 公共语料集合（B1/B2 面经知识库）：只读全局知识，所有用户可检索。
# 与 per-user ``knowledge_{user_id}`` 命名隔离，互不串扰。
CORPUS_KINDS = ("interview_hub", "interview_qa", "resume_samples")


def corpus_collection_name(kind: str) -> str:
    """公共语料集合名（interview_hub 面经 / interview_qa 算法题库 / resume_samples 简历范文）。

    - 每个公共语料一个独立集合，asset 以 ``user_id=0`` 写入（公共资产，所有用户可检索）
    - 集合内全部为 ``is_latest=True`` 的 v1 快照；检索显式 ``where={is_latest: True}`` 全量过滤
    - 集中定义合法类型，避免调用方拼错集合名（校验不通过抛 ValueError）
    """
    if kind not in CORPUS_KINDS:
        raise ValueError(f"未知公共语料类型: {kind}（可选: {', '.join(CORPUS_KINDS)}）")
    return kind


def cleanup_orphan_segments() -> int:
    """清理 ChromaDB delete_collection 在 Windows 上留下的孤儿 HNSW 目录。

    可在运行期调用，用于清理 delete_collection 后产生的孤儿文件。

    Returns:
        清理的孤儿目录数量
    """
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


# 保留旧函数名作为别名（兼容启动期调用）
_cleanup_orphan_segments = cleanup_orphan_segments
