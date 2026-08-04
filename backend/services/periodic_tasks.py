"""后台周期任务：stale 清扫 / 记忆整合 / 孤儿扫描。

机制：lifespan 起 asyncio 后台循环（`while True: sleep → run`），
配合 Redis 分布式锁防多实例重复执行（`_run_locked`）。
开关 `PERIODIC_TASKS_ENABLED`（默认 False）显式开启，**不用 ENVIRONMENT 判断**，
保证测试（TestClient 触发 lifespan）零污染。

每个 task 独立；`asyncio.sleep` 是唯一可取消点，shutdown 时 `task.cancel()`
可干净退出（consolidate 单轮可能跑很久，cancel 中断可接受——幂等）。
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable

from core.config import settings
from core.distributed_lock import acquire_periodic_lock, release_periodic_lock

logger = logging.getLogger(__name__)


async def _run_locked(
    name: str,
    ttl_seconds: int,
    coro_factory: Callable[[], Awaitable[None]],
) -> None:
    """分布式锁包裹执行；无锁/异常均不冒泡（周期循环继续）。"""
    lock_id = await acquire_periodic_lock(name, ttl_seconds)
    if lock_id is None:
        logger.info("periodic:%s 已被其他实例持有，跳过本轮", name)
        return
    try:
        await coro_factory()
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("periodic:%s 执行失败", name)
    finally:
        await release_periodic_lock(name, lock_id)


async def _loop(
    name: str,
    interval_seconds: int,
    lock_ttl_seconds: int,
    coro_factory: Callable[[], Awaitable[None]],
) -> None:
    """周期循环：sleep 后执行（sleep 是唯一可取消点）。"""
    while True:
        await asyncio.sleep(interval_seconds)
        await _run_locked(name, lock_ttl_seconds, coro_factory)


async def consolidate_all_memories() -> None:
    """对所有有 L4 记忆的用户执行记忆整合（consolidate）。

    活跃用户来源：Chroma `memory_` 前缀集合（比查 DB 更准，只处理真实有记忆的用户）。
    逐个 try/except 兜底——consolidate 本身无 try，单用户失败不影响其余。
    """
    try:
        from services.rag.clients import get_chroma_client
        from services.memory.consolidation import consolidate

        client = get_chroma_client()
        collections = client.list_collections()
        user_ids: list[int] = []
        for coll in collections:
            name = getattr(coll, "name", coll)
            if isinstance(name, str) and name.startswith("memory_"):
                try:
                    user_ids.append(int(name.split("_", 1)[1]))
                except (ValueError, IndexError):
                    continue
        user_ids = user_ids[: settings.MEMORY_CONSOLIDATE_MAX_USERS_PER_RUN]
        for uid in user_ids:
            try:
                result = await consolidate(uid)
                logger.info(
                    "memory consolidate user=%d: expired=%d merged=%d deleted=%d remaining=%d",
                    uid, result.get("expired", 0), result.get("merged", 0),
                    result.get("deleted", 0), result.get("remaining", 0),
                )
            except Exception:
                logger.exception("memory consolidate 失败 user=%d", uid)
    except Exception:
        logger.exception("consolidate_all_memories 失败")


async def run_orphan_scan_log() -> None:
    """执行孤儿扫描并输出诊断日志（只报告，不删除）。"""
    try:
        from services.resume_cleanup import orphan_scan

        orphans = await orphan_scan()
        if orphans.get("files") or orphans.get("chromadb"):
            logger.warning(
                "孤儿扫描: files=%d chromadb=%d | files=%s chromadb=%s",
                len(orphans.get("files", [])), len(orphans.get("chromadb", [])),
                orphans.get("files"), orphans.get("chromadb"),
            )
        else:
            logger.info("孤儿扫描: 无孤儿文件/collection")
    except Exception:
        logger.exception("孤儿扫描失败")


async def start_periodic_tasks() -> list[asyncio.Task]:
    """启动周期任务。开关关闭返回空列表（测试/开发零污染）。"""
    if not settings.PERIODIC_TASKS_ENABLED:
        return []

    from services.resume_cleanup import cleanup_stale_processing

    tasks = [
        asyncio.create_task(
            _loop(
                "stale_cleanup",
                settings.STALE_CLEANUP_INTERVAL_MINUTES * 60,
                600,
                cleanup_stale_processing,
            )
        ),
        asyncio.create_task(
            _loop(
                "consolidate",
                settings.MEMORY_CONSOLIDATE_INTERVAL_HOURS * 3600,
                3600,
                consolidate_all_memories,
            )
        ),
        asyncio.create_task(
            _loop(
                "orphan_scan",
                settings.ORPHAN_SCAN_INTERVAL_HOURS * 3600,
                1800,
                run_orphan_scan_log,
            )
        ),
    ]
    return tasks
