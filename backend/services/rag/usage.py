"""LLM 调用统一记账服务。

记录全量 LLM 调用的 token 消耗（prompt / completion / total / call_count），
按用户+日期聚合到 Redis（7 天 TTL）。

设计原则：
- 只记成功调用（调用方保证在成功后才调用）
- Redis 挂时降级为 InMemoryRedis，不阻塞主流程
- 失败日志限频（60s 内最多一条），避免日志爆炸
"""

import logging
import time
from datetime import datetime, timezone

from core.redis_client import get_redis

logger = logging.getLogger(__name__)

# 失败日志限频：连续 Redis 故障时减少日志噪音
_LAST_FAIL_LOG_TIME: float = 0.0
_FAIL_LOG_INTERVAL_SEC: int = 60


async def record_llm_usage(user_id: int, prompt_tokens: int, completion_tokens: int) -> None:
    """记录 LLM token 使用量到 Redis（日统计）。

    Args:
        user_id: 用户 ID
        prompt_tokens: 输入 token 数
        completion_tokens: 输出 token 数

    Redis Key 格式（string，incrby）：
        llm_usage:{user_id}:{YYYYMMDD}:prompt
        llm_usage:{user_id}:{YYYYMMDD}:completion
        llm_usage:{user_id}:{YYYYMMDD}:total
        llm_usage:{user_id}:{YYYYMMDD}:calls

    TTL: 7 天
    """
    if prompt_tokens < 0 or completion_tokens < 0:
        return

    total = prompt_tokens + completion_tokens
    if total <= 0:
        return

    date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
    base = f"llm_usage:{user_id}:{date_str}"

    try:
        redis = await get_redis()
        # 并行递增 4 个计数器（InMemoryRedis 不支持 pipeline，逐个调用）
        await redis.incrby(f"{base}:prompt", prompt_tokens)
        await redis.incrby(f"{base}:completion", completion_tokens)
        await redis.incrby(f"{base}:total", total)
        await redis.incrby(f"{base}:calls", 1)

        # 设置 7 天过期（对新 key 生效，已存在的 key 续期不影响）
        ttl = 86400 * 7
        await redis.expire(f"{base}:prompt", ttl)
        await redis.expire(f"{base}:completion", ttl)
        await redis.expire(f"{base}:total", ttl)
        await redis.expire(f"{base}:calls", ttl)
    except Exception:
        _log_redis_fail_limited()


def _log_redis_fail_limited() -> None:
    """限频记录 Redis 降级日志。"""
    global _LAST_FAIL_LOG_TIME
    now = time.time()
    if now - _LAST_FAIL_LOG_TIME >= _FAIL_LOG_INTERVAL_SEC:
        _LAST_FAIL_LOG_TIME = now
        logger.warning("Redis 不可用，LLM usage 记账降级（限频日志，每 %ds 一次）", _FAIL_LOG_INTERVAL_SEC)
