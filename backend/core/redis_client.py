"""Redis 连接单例，含降级策略。

Redis 不可用时返回 None，调用方自行降级为内存模式。

降级策略（按环境）：
- development/testing：按 ENVIRONMENT 标签直接跳过，零开销
- staging/production：尝试连接，失败后降级
"""

import logging

from core.config import settings

logger = logging.getLogger(__name__)

_redis = None


async def get_redis():
    """获取 Redis 客户端。不可用时返回 None，调用方自行降级。"""
    # 开发/测试环境：不尝试连接，直接跳过
    if settings.ENVIRONMENT in ("development", "testing"):
        return None

    global _redis
    if _redis is not None:
        try:
            await _redis.ping()
            return _redis
        except Exception:
            _redis = None

    try:
        import redis.asyncio as aioredis

        _redis = aioredis.from_url(
            settings.REDIS_URL,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
        )
        await _redis.ping()
        logger.info("Redis connected")
        return _redis
    except Exception:
        logger.warning("Redis unavailable, using in-memory fallback")
        return None


async def close_redis():
    """关闭 Redis 连接。"""
    global _redis
    if _redis is not None:
        await _redis.close()
        _redis = None
