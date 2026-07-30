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
        return None


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
