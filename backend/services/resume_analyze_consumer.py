"""简历分析任务消费者。

由 RabbitMQ 消费者触发，执行以下流程：
1. 获取分布式锁（防止并发）
2. 检查 Redis 缓存（幂等，已分析则跳过）
3. 检查 token 限额（后台分析计入限额）
4. 批量调用 LLM 分析 4 种类型
5. 写入 Redis 缓存
6. 推送 WebSocket 通知（完成/失败）
7. 更新 token 消耗

降级策略：
- Redis 不可用：跳过缓存检查，直接调用 LLM
- Token 不足：跳过分析，推送"额度不足"通知
- LLM 失败：重试 3 次，超过则入死信队列
"""

import asyncio
import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from core.config import settings
from core.distributed_lock import acquire_lock, release_lock
from core.redis_client import get_redis
from core.websocket_manager import ws_manager
from services.analyze_service import analyze_resume
from services.resume_analysis_cache import (
    VALID_ANALYSIS_TYPES,
    get_full_analysis_cache,
    set_full_analysis_cache,
)
from services.token_quota import check_quota, record_usage

logger = logging.getLogger(__name__)

BEIJING_TZ = timezone(timedelta(hours=8))

# 分析超时（秒）
ANALYZE_TIMEOUT = 120


async def process_analyze_task(payload: dict) -> None:
    """处理单个分析任务。

    此函数可被：
    - RabbitMQ 消费者直接调用（异步上下文）
    - BackgroundTasks 降级调用
    - 同步降级调用

    Args:
        payload: 消息体，包含 resume_id, user_id, filename 等
    """
    resume_id = payload.get("resume_id")
    user_id = payload.get("user_id")
    filename = payload.get("filename", "unknown")
    retry_count = payload.get("retry_count", 0)

    if resume_id is None or user_id is None:
        logger.error("分析任务缺少必要参数: %s", payload)
        return

    logger.info(
        "开始处理分析任务: resume_id=%d, user_id=%d, retry=%d",
        resume_id, user_id, retry_count,
    )

    lock_id = None
    try:
        # 1. 获取分布式锁
        lock_id = await acquire_lock(user_id, resume_id)
        if lock_id is None:
            logger.info(
                "用户%d已有分析任务在执行，跳过 resume_id=%d",
                user_id, resume_id,
            )
            return

        # 2. 检查 Redis 缓存（幂等）
        cached = await get_full_analysis_cache(resume_id)
        if cached is not None:
            logger.info("分析缓存已存在，跳过: resume_id=%d", resume_id)
            await _push_notification(user_id, resume_id, "completed", cached)
            return

        # 3. 检查 token 限额
        allowed, quota_error = await check_quota(user_id)
        if not allowed:
            logger.warning(
                "Token 额度不足，跳过后台分析: user_id=%d, error=%s",
                user_id, quota_error,
            )
            await _push_notification(user_id, resume_id, "quota_exceeded", {
                "message": quota_error,
            })
            return

        # 4. 初始化数据库 session
        from core.database import async_session
        async with async_session() as db:
            # 5. 批量分析 4 种类型
            results = {}
            total_tokens = 0

            for analysis_type in VALID_ANALYSIS_TYPES:
                try:
                    result = await asyncio.wait_for(
                        analyze_resume(db, user_id, resume_id, analysis_type),
                        timeout=ANALYZE_TIMEOUT,
                    )
                    results[analysis_type] = result

                    # 估算 token 消耗（如果有 usage 信息）
                    usage = result.get("usage", {})
                    total_tokens += usage.get("total_tokens", 0)

                    logger.info(
                        "分析完成: resume_id=%d, type=%s",
                        resume_id, analysis_type,
                    )

                except asyncio.TimeoutError:
                    logger.error(
                        "分析超时: resume_id=%d, type=%s",
                        resume_id, analysis_type,
                    )
                    raise
                except Exception as e:
                    logger.exception(
                        "分析失败: resume_id=%d, type=%s: %s",
                        resume_id, analysis_type, e,
                    )
                    raise

            # 6. 写入完整缓存
            await set_full_analysis_cache(resume_id, results)

            # 7. 记录 token 消耗
            if total_tokens > 0:
                await record_usage(user_id, total_tokens)

            # 8. 推送完成通知
            await _push_notification(user_id, resume_id, "completed", results)

            logger.info(
                "分析任务完成: resume_id=%d, user_id=%d, tokens=%d",
                resume_id, user_id, total_tokens,
            )

    except Exception as e:
        logger.exception(
            "分析任务失败: resume_id=%d, user_id=%d, retry=%d: %s",
            resume_id, user_id, retry_count, e,
        )

        # 推送失败通知
        await _push_notification(user_id, resume_id, "failed", {
            "message": str(e),
            "retry_count": retry_count,
        })

        # 重新抛出让 MQ 决定是否重试
        raise

    finally:
        # 释放分布式锁
        if lock_id:
            await release_lock(user_id, lock_id)


async def _push_notification(
    user_id: int,
    resume_id: int,
    status: str,
    data: Optional[dict] = None,
) -> None:
    """通过 WebSocket 推送分析状态通知。

    Args:
        user_id: 用户 ID
        resume_id: 简历 ID
        status: 状态（completed/failed/quota_exceeded）
        data: 附加数据
    """
    message = {
        "type": "analysis_complete" if status == "completed" else "analysis_update",
        "status": status,
        "resume_id": resume_id,
        "user_id": user_id,
        "timestamp": datetime.now(BEIJING_TZ).isoformat(),
    }
    if data:
        # 清理过大的数据（只保留摘要）
        if status == "completed" and isinstance(data, dict):
            message["data"] = _summarize_results(data)
        else:
            message["data"] = data

    await ws_manager.send_to_user(user_id, message)


def _summarize_results(results: dict) -> dict:
    """精简分析结果，避免 WebSocket 消息过大。"""
    summary = {}
    for analysis_type in VALID_ANALYSIS_TYPES:
        if analysis_type in results:
            item = results[analysis_type]
            if isinstance(item, dict):
                summary[analysis_type] = {
                    "analysis_type": item.get("analysis_type"),
                    "has_content": bool(item.get("analysis")),
                }
                # score 类型附带分数
                if analysis_type == "score" and "scores" in item:
                    summary[analysis_type]["scores"] = item["scores"]
    return summary
