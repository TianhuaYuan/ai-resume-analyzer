"""T28: 编辑锁服务 — Redis 分布式锁 + TTL 2min + 心跳续期。

职责：
- acquire_edit_lock: 获取简历编辑锁（SET NX EX，互斥）
- renew_edit_lock: 心跳续期（延长 TTL，防编辑中途过期）
- release_edit_lock: 释放锁（Lua CAS，防止释放他人锁）
- is_edit_locked: 查询锁状态

设计依据：
- plan.md T28: 短事务独立 commit + 编辑锁 TTL 2min 心跳
- spec A5#66: 草稿 last-write-wins，但 AI 工具写操作需防并发冲突
- Redis SET NX EX 实现互斥 + Lua eval 实现 CAS 释放

锁 Key 格式: edit_lock:{resume_id}
锁 Value: {user_id}:{timestamp}（用于 CAS 释放验证）
TTL: 120s（2 分钟），前端每 60s 发心跳续期
"""

import logging
import uuid

from core.redis_client import get_redis

logger = logging.getLogger(__name__)

# 编辑锁 TTL（秒）：2 分钟
EDIT_LOCK_TTL: int = 120

# 锁 Key 前缀
_LOCK_PREFIX = "edit_lock:"


def _lock_key(resume_id: int) -> str:
    """生成锁 Key。"""
    return f"{_LOCK_PREFIX}{resume_id}"


def _lock_value(user_id: int) -> str:
    """生成锁 Value（含 user_id 和唯一 token，用于 CAS 释放）。"""
    return f"{user_id}:{uuid.uuid4().hex[:8]}"


# Lua 脚本：CAS 释放锁（只有 value 匹配时才删除）
_RELEASE_SCRIPT = """
if redis.call("GET", KEYS[1]) == ARGV[1] then
    return redis.call("DEL", KEYS[1])
else
    return 0
end
"""

# Lua 脚本：CAS 续期（只有 value 匹配时才 EXPIRE）
_RENEW_SCRIPT = """
if redis.call("GET", KEYS[1]) == ARGV[1] then
    return redis.call("EXPIRE", KEYS[1], ARGV[2])
else
    return 0
end
"""


async def acquire_edit_lock(
    resume_id: int,
    user_id: int,
    ttl: int = EDIT_LOCK_TTL,
) -> str | None:
    """获取编辑锁。

    使用 Redis SET NX EX 实现互斥：
    - 成功获取 → 返回锁 token（用于后续续期/释放）
    - 已被他人持有 → 返回 None

    Args:
        resume_id: 简历 ID
        user_id: 用户 ID
        ttl: 锁有效期（秒），默认 120s

    Returns:
        锁 token 字符串（成功）或 None（失败）
    """
    redis = await get_redis()
    key = _lock_key(resume_id)
    value = _lock_value(user_id)

    # SET NX EX: 仅当 key 不存在时设置，并带过期时间
    acquired = await redis.set(key, value, nx=True, ex=ttl)

    if acquired:
        logger.info("Edit lock acquired: resume=%d, user=%d", resume_id, user_id)
        return value

    # 获取失败，检查是否是自己已持有（同 user 重新获取）
    existing = await redis.get(key)
    if existing and existing.startswith(f"{user_id}:"):
        # 自己已持有锁，续期并返回新 token
        await redis.set(key, value, ex=ttl)
        logger.info("Edit lock re-acquired (same user): resume=%d, user=%d", resume_id, user_id)
        return value

    logger.info("Edit lock failed (held by another): resume=%d, user=%d", resume_id, user_id)
    return None


async def renew_edit_lock(
    resume_id: int,
    user_id: int,
    lock_token: str,
    ttl: int = EDIT_LOCK_TTL,
) -> bool:
    """心跳续期。

    只有锁 token 匹配时才续期，防止续期他人的锁。

    Args:
        resume_id: 简历 ID
        user_id: 用户 ID
        lock_token: acquire 时返回的锁 token
        ttl: 新的过期时间（秒）

    Returns:
        True: 续期成功
        False: 锁不存在或 token 不匹配
    """
    redis = await get_redis()
    key = _lock_key(resume_id)

    # 使用 Lua CAS 续期
    try:
        result = await redis.eval(_RENEW_SCRIPT, 1, key, lock_token, str(ttl))
        if result == 1:
            logger.debug("Edit lock renewed: resume=%d, user=%d", resume_id, user_id)
            return True
        logger.warning("Edit lock renew failed (token mismatch or expired): resume=%d", resume_id)
        return False
    except Exception:
        # 兜底：eval 不支持（如某些内存实现），回退到 get + EXPIRE（CAS 语义）
        existing = await redis.get(key)
        if existing == lock_token:
            await redis.expire(key, ttl)
            logger.debug("Edit lock renewed (fallback): resume=%d", resume_id)
            return True
        logger.warning("Edit lock renew failed (fallback): resume=%d", resume_id)
        return False


async def release_edit_lock(
    resume_id: int,
    user_id: int,
    lock_token: str,
) -> bool:
    """释放编辑锁。

    使用 Lua CAS 释放：只有锁 token 匹配时才删除，防止释放他人的锁。

    Args:
        resume_id: 简历 ID
        user_id: 用户 ID
        lock_token: acquire 时返回的锁 token

    Returns:
        True: 释放成功
        False: 锁不存在或 token 不匹配
    """
    redis = await get_redis()
    key = _lock_key(resume_id)

    try:
        result = await redis.eval(_RELEASE_SCRIPT, 1, key, lock_token)
        if result == 1:
            logger.info("Edit lock released: resume=%d, user=%d", resume_id, user_id)
            return True
        logger.warning("Edit lock release failed (token mismatch): resume=%d", resume_id)
        return False
    except Exception:
        # 回退方案
        existing = await redis.get(key)
        if existing == lock_token:
            await redis.delete(key)
            logger.info("Edit lock released (fallback): resume=%d", resume_id)
            return True
        logger.warning("Edit lock release failed (fallback): resume=%d", resume_id)
        return False


async def is_edit_locked(resume_id: int) -> bool:
    """查询简历是否被锁定。

    Args:
        resume_id: 简历 ID

    Returns:
        True: 已锁定
        False: 未锁定
    """
    redis = await get_redis()
    key = _lock_key(resume_id)
    existing = await redis.get(key)
    return existing is not None


async def get_lock_holder(resume_id: int) -> int | None:
    """获取当前锁持有者的 user_id。

    Args:
        resume_id: 简历 ID

    Returns:
        user_id（如果锁定）或 None（未锁定）
    """
    redis = await get_redis()
    key = _lock_key(resume_id)
    existing = await redis.get(key)
    if existing and ":" in existing:
        try:
            return int(existing.split(":")[0])
        except (ValueError, IndexError):
            return None
    return None
