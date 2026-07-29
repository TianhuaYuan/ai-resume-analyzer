"""简历分析结果 Redis 缓存服务。

Key 格式: resume_analysis:{resume_id}:{analysis_type}
TTL: 7 天（简历内容不常变更）

分析和对比功能复用同一份缓存：
- 分析页单类型查询 → 先查缓存，命中跳过 LLM
- 对比功能需要 4 种类型完整结果 → 批量查缓存，缺失的类型补齐 LLM 调用
"""

import json
import logging
from typing import Optional

from core.config import settings
from core.redis_client import get_redis

logger = logging.getLogger(__name__)

# 4 种合法的分析类型
VALID_ANALYSIS_TYPES = ("summary", "skills", "experience", "score")

# 默认 TTL：7 天
DEFAULT_TTL = 7 * 24 * 3600


def _cache_key(resume_id: int, analysis_type: str) -> str:
    """生成缓存 key。格式: resume_analysis:{resume_id}:{analysis_type}"""
    return f"resume_analysis:{resume_id}:{analysis_type}"


async def get_analysis_cache(
    resume_id: int, analysis_type: str
) -> Optional[dict]:
    """获取单份分析结果的缓存。

    Args:
        resume_id: 简历 ID
        analysis_type: 分析类型（summary/skills/experience/score）

    Returns:
        命中返回解析后的 dict，未命中 / Redis 不可用 / 解析失败返回 None
    """
    if analysis_type not in VALID_ANALYSIS_TYPES:
        logger.warning("非法 analysis_type: %s", analysis_type)
        return None

    try:
        redis = await get_redis()
        if redis is None:
            return None

        key = _cache_key(resume_id, analysis_type)
        raw = await redis.get(key)
        if raw is None:
            return None

        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            logger.warning(
                "分析缓存内容损坏，key=%s，跳过缓存", key
            )
            return None

    except Exception as e:
        logger.exception("获取分析缓存失败 resume_id=%s type=%s: %s",
                         resume_id, analysis_type, e)
        return None


async def set_analysis_cache(
    resume_id: int,
    analysis_type: str,
    value: dict,
    ttl_seconds: int = DEFAULT_TTL,
) -> bool:
    """写入单份分析结果到缓存。

    Args:
        resume_id: 简历 ID
        analysis_type: 分析类型
        value: 要缓存的 dict（必须可 JSON 序列化）
        ttl_seconds: TTL，默认 7 天

    Returns:
        True 写入成功，False 写入失败（Redis 不可用或序列化错误）
    """
    if analysis_type not in VALID_ANALYSIS_TYPES:
        logger.warning("非法 analysis_type: %s，跳过写入缓存", analysis_type)
        return False

    try:
        redis = await get_redis()
        if redis is None:
            return False

        key = _cache_key(resume_id, analysis_type)
        serialized = json.dumps(value, ensure_ascii=False)
        await redis.setex(key, ttl_seconds, serialized)
        return True

    except (TypeError, ValueError) as e:
        # JSON 序列化失败
        logger.exception("序列化分析缓存失败 resume_id=%s type=%s: %s",
                         resume_id, analysis_type, e)
        return False
    except Exception as e:
        logger.exception("写入分析缓存失败 resume_id=%s type=%s: %s",
                         resume_id, analysis_type, e)
        return False


async def invalidate_resume_cache(resume_id: int) -> bool:
    """删除某简历的全部分析缓存（4 种类型）。

    适用于重新上传/重新解析简历后需要清空旧缓存的场景。

    Returns:
        True 执行了删除操作，False Redis 不可用
    """
    try:
        redis = await get_redis()
        if redis is None:
            return False

        keys = [_cache_key(resume_id, t) for t in VALID_ANALYSIS_TYPES]
        await redis.delete(*keys)
        return True

    except Exception as e:
        logger.exception("失效分析缓存失败 resume_id=%s: %s", resume_id, e)
        return False


async def get_full_analysis_cache(
    resume_id: int,
) -> Optional[dict[str, dict]]:
    """批量获取一份简历的完整分析结果（4 种类型都命中才返回）。

    用于对比功能：只有完整拿到 4 种分析结果才能用缓存，
    否则返回 None，由调用方补齐缺失的 LLM 调用。

    Returns:
        {"summary": {...}, "skills": {...}, "experience": {...}, "score": {...}}
        或 None（任一类型未命中）
    """
    try:
        redis = await get_redis()
        if redis is None:
            return None

        # 先批量拿全部 key（mget 接收位置参数，用 *keys 解包）
        keys = [_cache_key(resume_id, t) for t in VALID_ANALYSIS_TYPES]
        raw_values = await redis.mget(*keys)

        result: dict[str, dict] = {}
        for analysis_type, raw in zip(VALID_ANALYSIS_TYPES, raw_values):
            if raw is None:
                logger.info(
                    "完整缓存未命中 resume_id=%s 缺少 type=%s",
                    resume_id, analysis_type,
                )
                return None
            try:
                result[analysis_type] = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                logger.warning(
                    "完整缓存内容损坏 resume_id=%s type=%s",
                    resume_id, analysis_type,
                )
                return None

        return result

    except Exception as e:
        logger.exception("批量获取完整分析缓存失败 resume_id=%s: %s",
                         resume_id, e)
        return None


async def set_full_analysis_cache(
    resume_id: int,
    full_result: dict[str, dict],
    ttl_seconds: int = DEFAULT_TTL,
) -> bool:
    """批量写入完整分析结果缓存（对比功能 LLM 调用后的结果）。

    Args:
        resume_id: 简历 ID
        full_result: {analysis_type: value_dict}，应包含 4 种合法类型
        ttl_seconds: TTL

    Returns:
        True 全部写入成功，False 任一失败
    """
    try:
        redis = await get_redis()
        if redis is None:
            return False

        all_ok = True
        for analysis_type in VALID_ANALYSIS_TYPES:
            if analysis_type not in full_result:
                logger.warning(
                    "完整缓存缺少 type=%s，跳过该类型写入",
                    analysis_type,
                )
                all_ok = False
                continue
            ok = await set_analysis_cache(
                resume_id, analysis_type, full_result[analysis_type], ttl_seconds
            )
            if not ok:
                all_ok = False

        return all_ok

    except Exception as e:
        logger.exception("批量写入完整分析缓存失败 resume_id=%s: %s",
                         resume_id, e)
        return False
