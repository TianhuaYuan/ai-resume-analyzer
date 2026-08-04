"""记忆提炼节流触发器 — 对话结束后异步提炼写 L4。

开关（MEMORY_EXTRACTION_ENABLED，默认 False）：
- 关闭：直接返回 False，不创建任何任务（测试/开发零污染）。
- 开启：按用户节流（Redis SET NX EX / in-process dict 回退），
  每 MEMORY_EXTRACTION_INTERVAL_SEC 最多提炼一次，避免每回合烧 token。

任何异常只记录、返回 False，不影响主流程（对话应答）。
"""

import logging
import time

from core.config import settings

logger = logging.getLogger(__name__)

# Redis 不可用时的 in-process 回退节流表：user_id -> last_extract_ts
# （多 worker 部署会放大到 worker 数倍，可接受；Redis 可用时走 SET NX 全局协调）
_extract_lock: dict[int, float] = {}


async def _throttle_acquire(user_id: int) -> bool:
    """按用户节流：Redis SET NX EX 优先，失败回退 in-process dict。"""
    try:
        from core.redis_client import get_redis

        redis = await get_redis()
        if redis is not None:
            ok = await redis.set(
                f"memory_extract:{user_id}",
                "1",
                nx=True,
                ex=settings.MEMORY_EXTRACTION_INTERVAL_SEC,
            )
            return bool(ok)
    except Exception:
        pass  # Redis 不可用 → 回退 in-process

    now = time.time()
    if now - _extract_lock.get(user_id, 0.0) < settings.MEMORY_EXTRACTION_INTERVAL_SEC:
        return False
    _extract_lock[user_id] = now
    return True


async def maybe_extract_memories(user_id: int, conversation_text: str) -> bool:
    """对话结束后节流触发记忆提炼。成功触发返回 True，否则 False（不抛异常）。"""
    if not settings.MEMORY_EXTRACTION_ENABLED:
        return False
    if not await _throttle_acquire(user_id):
        return False
    try:
        from services.memory.extraction import extract_and_save_memories

        await extract_and_save_memories(
            user_id=user_id,
            conversation_text=conversation_text,
        )
        return True
    except Exception:
        logger.warning("记忆提炼失败（不影响主流程）: user=%d", user_id, exc_info=True)
        return False
