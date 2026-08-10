"""分布式锁服务。

基于 Redis SET NX 实现，用于防止同一用户同时触发多个分析任务。
避免批量上传时 LLM API 被并发打爆。
"""

import logging
import uuid
from typing import Optional

from core.redis_client import get_redis

logger = logging.getLogger(__name__)

# 锁 key 前缀
LOCK_PREFIX = "analysis_lock:"
INDEX_LOCK_PREFIX = "index_lock:"

# 默认锁超时（秒）
DEFAULT_LOCK_TTL = 120


async def acquire_lock(
    user_id: int,
    resume_id: int,
    ttl_seconds: int = DEFAULT_LOCK_TTL,
) -> Optional[str]:
    """获取分布式锁。

    Args:
        user_id: 用户 ID
        resume_id: 简历 ID
        ttl_seconds: 锁超时时间（秒）

    Returns:
        lock_id 获取成功返回唯一锁标识（用于释放），None 表示获取失败
    """
    try:
        redis = await get_redis()
        if redis is None:
            logger.warning("Redis 不可用，跳过分布式锁获取")
            return str(uuid.uuid4())  # 降级：直接返回假锁 ID

        lock_key = f"{LOCK_PREFIX}{user_id}:{resume_id}"
        lock_id = str(uuid.uuid4())

        # SET NX EX：不存在时设置，带过期时间
        acquired = await redis.set(lock_key, lock_id, nx=True, ex=ttl_seconds)
        if acquired:
            logger.debug(
                "分布式锁获取成功 user_id=%s resume_id=%s",
                user_id, resume_id,
            )
            return lock_id
        else:
            logger.debug(
                "分布式锁获取失败 user_id=%s resume_id=%s（已有分析任务在执行）",
                user_id, resume_id,
            )
            return None

    except Exception as e:
        logger.exception("分布式锁获取异常 user_id=%s: %s", user_id, e)
        return f"local-fallback:{uuid.uuid4()}"


async def release_lock(user_id: int, resume_id: int, lock_id: str) -> bool:
    """释放分布式锁。

    只释放自己持有的锁（通过比对 lock_id 防止误删）。

    Args:
        user_id: 用户 ID
        lock_id: 获取锁时返回的唯一标识

    Returns:
        True 释放成功，False 释放失败
    """
    try:
        redis = await get_redis()
        if redis is None:
            return True  # 降级：Redis 不可用时直接放行

        lock_key = f"{LOCK_PREFIX}{user_id}:{resume_id}"

        # Lua 脚本：原子性地检查并删除锁
        lua_script = """
        if redis.call("GET", KEYS[1]) == ARGV[1] then
            return redis.call("DEL", KEYS[1])
        else
            return 0
        end
        """
        result = await redis.eval(lua_script, 1, lock_key, lock_id)
        if result == 1:
            logger.debug("分布式锁释放成功 user_id=%s resume_id=%s", user_id, resume_id)
            return True
        else:
            logger.debug(
                "分布式锁释放失败 user_id=%s resume_id=%s（锁已过期或被他人持有）",
                user_id, resume_id,
            )
            return False

    except Exception as e:
        logger.exception("分布式锁释放异常 user_id=%s: %s", user_id, e)
        return False


# ─────────────────────────────────────────────────────────────
# T6：索引分布式锁（按 user_id + asset_type + asset_id 粒度）
# 防止同一资产多个请求同时触发懒重建。
# ─────────────────────────────────────────────────────────────

async def _acquire_lock_key(lock_key: str, ttl_seconds: int) -> Optional[str]:
    """通用 SET NX 分布式锁获取。Redis 不可用时降级为返回假锁 ID。"""
    try:
        redis = await get_redis()
        if redis is None:
            logger.warning("Redis 不可用，跳过分布式锁获取（key=%s）", lock_key)
            return str(uuid.uuid4())  # 降级：直接返回假锁 ID
        lock_id = str(uuid.uuid4())
        acquired = await redis.set(lock_key, lock_id, nx=True, ex=ttl_seconds)
        if acquired:
            logger.debug("分布式锁获取成功 key=%s", lock_key)
            return lock_id
        logger.debug("分布式锁获取失败 key=%s（已有持有者）", lock_key)
        return None
    except Exception as e:
        logger.exception("分布式锁获取异常 key=%s: %s", lock_key, e)
        return None


async def _release_lock_key(lock_key: str, lock_id: str) -> bool:
    """通用分布式锁释放（Lua 比对 lock_id 防误删）。"""
    try:
        redis = await get_redis()
        if redis is None:
            return True  # 降级：Redis 不可用时直接放行
        lua_script = """
        if redis.call("GET", KEYS[1]) == ARGV[1] then
            return redis.call("DEL", KEYS[1])
        else
            return 0
        end
        """
        result = await redis.eval(lua_script, 1, lock_key, lock_id)
        return result == 1
    except Exception as e:
        logger.exception("分布式锁释放异常 key=%s: %s", lock_key, e)
        return False


async def acquire_index_lock(
    user_id: int,
    asset_type: str,
    asset_id: int,
    ttl_seconds: int = DEFAULT_LOCK_TTL,
) -> Optional[str]:
    """按 (user_id, asset_type, asset_id) 获取索引分布式锁（T6）。"""
    return await _acquire_lock_key(
        f"{INDEX_LOCK_PREFIX}{user_id}:{asset_type}:{asset_id}", ttl_seconds
    )


async def release_index_lock(
    user_id: int,
    asset_type: str,
    asset_id: int,
    lock_id: str,
) -> bool:
    """释放索引分布式锁。"""
    return await _release_lock_key(
        f"{INDEX_LOCK_PREFIX}{user_id}:{asset_type}:{asset_id}", lock_id
    )


# ─────────────────────────────────────────────────────────────
# 周期任务分布式锁（防止多实例重复执行同一周期任务）
# ─────────────────────────────────────────────────────────────

async def acquire_periodic_lock(name: str, ttl_seconds: int) -> Optional[str]:
    """获取周期任务分布式锁。Redis 不可用时降级返回假锁 ID（单实例放行）。"""
    return await _acquire_lock_key(f"periodic:{name}", ttl_seconds)


async def release_periodic_lock(name: str, lock_id: str) -> bool:
    """释放周期任务分布式锁。"""
    return await _release_lock_key(f"periodic:{name}", lock_id)
