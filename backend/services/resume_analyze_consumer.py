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
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from core.config import settings
from core.distributed_lock import acquire_lock, release_lock
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


async def _resume_exists(resume_id: int) -> bool:
    """查询简历是否仍存在（用户删除后丢弃僵尸任务，避免无谓的 LLM 分析 + 重试）。

    DB 查询失败时放行（返回 True），交给 analyze_resume 兜底，不因校验本身阻断任务。
    """
    from sqlalchemy import select

    from core.database import AsyncSessionLocal as async_session
    from models.resume import Resume

    try:
        async with async_session() as db:
            row = await db.execute(select(Resume.id).where(Resume.id == resume_id))
            return row.scalar_one_or_none() is not None
    except Exception:
        logger.warning("简历存在性校验失败，放行任务: resume_id=%d", resume_id, exc_info=True)
        return True


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
    retry_count = payload.get("retry_count", 0)

    if resume_id is None or user_id is None:
        logger.error("分析任务缺少必要参数: %s", payload)
        return

    # 用户可能在任务排队期间删除了简历 → 丢弃僵尸任务（不触发 LLM 分析、不重试）
    if not await _resume_exists(resume_id):
        logger.warning("分析任务对应简历已删除，丢弃: resume_id=%d", resume_id)
        return

    logger.info(
        "开始处理分析任务: resume_id=%d, user_id=%d, retry=%d",
        resume_id,
        user_id,
        retry_count,
    )

    lock_id = None
    try:
        # 1. 获取分布式锁（P2-6：TTL 显式设 > 任务最大时长，防锁中途过期
        #    导致同 (user,resume) 并发二进分析）
        lock_id = await acquire_lock(
            user_id, resume_id, ttl_seconds=settings.ANALYZE_LOCK_TTL_SECONDS
        )
        if lock_id is None:
            logger.info(
                "用户%d已有分析任务在执行，跳过 resume_id=%d",
                user_id,
                resume_id,
            )
            # 通知前端分析已在运行
            await _push_progress(user_id, resume_id, 0, 4, "pending")
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
                user_id,
                quota_error,
            )
            await _push_notification(
                user_id,
                resume_id,
                "quota_exceeded",
                {
                    "message": quota_error,
                },
            )
            return

        # 4. 初始化数据库 session
        from core.database import AsyncSessionLocal as async_session

        async with async_session() as db:
            # 5. 批量分析 4 种类型（per-type 隔离：DeepInterview _guarded 对照——
            #    单类型失败 drop 记日志，绝不因一个类型毁掉整批已成功的工作）
            results = {}
            total_tokens = 0
            failed_types: list[str] = []

            total_types = len(VALID_ANALYSIS_TYPES)
            for i, analysis_type in enumerate(VALID_ANALYSIS_TYPES):
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
                        resume_id,
                        analysis_type,
                    )

                    # 每完成一项就推送进度
                    await _push_progress(user_id, resume_id, i + 1, total_types, analysis_type)

                except asyncio.TimeoutError:
                    logger.error(
                        "分析超时（跳过该类型）: resume_id=%d, type=%s",
                        resume_id,
                        analysis_type,
                    )
                    failed_types.append(analysis_type)
                except Exception as e:
                    logger.exception(
                        "分析失败（跳过该类型）: resume_id=%d, type=%s: %s",
                        resume_id,
                        analysis_type,
                        e,
                    )
                    failed_types.append(analysis_type)

            # 全部失败 → 视为任务失败（MQ 重试/死信）；部分失败 → 写部分缓存
            if not results:
                raise RuntimeError(f"所有分析类型均失败: {failed_types}")
            if failed_types:
                logger.warning(
                    "部分类型失败（写部分缓存，成功 %d/%d）: resume_id=%d, failed=%s",
                    len(results),
                    total_types,
                    resume_id,
                    failed_types,
                )

            # 6. 写入完整缓存（set_full_analysis_cache 缺类型自动跳过）
            await set_full_analysis_cache(resume_id, results)

            # 7. 记录 token 消耗
            if total_tokens > 0:
                await record_usage(user_id, total_tokens)

            # 8. 推送完成通知（附带 token 消耗）
            await _push_notification(user_id, resume_id, "completed", results, total_tokens)

            logger.info(
                "分析任务完成: resume_id=%d, user_id=%d, tokens=%d",
                resume_id,
                user_id,
                total_tokens,
            )

    except Exception as e:
        logger.exception(
            "分析任务失败: resume_id=%d, user_id=%d, retry=%d: %s",
            resume_id,
            user_id,
            retry_count,
            e,
        )

        # 推送失败通知
        await _push_notification(
            user_id,
            resume_id,
            "failed",
            {
                "message": str(e),
                "retry_count": retry_count,
            },
        )

        # 重新抛出让 MQ 决定是否重试
        raise

    finally:
        # 释放分布式锁
        if lock_id:
            await release_lock(user_id, resume_id, lock_id)


async def _push_progress(
    user_id: int,
    resume_id: int,
    completed: int,
    total: int,
    current_type: str,
) -> None:
    """推送分析进度到 WebSocket。"""
    type_labels = {
        "summary": "总结",
        "skills": "技能",
        "experience": "经历",
        "score": "评分",
    }
    type_label = type_labels.get(current_type, current_type)
    message = {
        "type": "analysis_progress",
        "resume_id": resume_id,
        "user_id": user_id,
        "completed": completed,
        "total": total,
        "current_type": current_type,
        "current_type_label": type_label,
        "timestamp": datetime.now(BEIJING_TZ).isoformat(),
    }
    await ws_manager.send_to_user(user_id, message)
    logger.info(
        "分析进度推送: resume_id=%d, %d/%d (当前: %s)",
        resume_id,
        completed,
        total,
        type_label,
    )


async def _push_notification(
    user_id: int,
    resume_id: int,
    status: str,
    data: Optional[dict] = None,
    token_used: int = 0,
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
    if token_used > 0:
        message["token_used"] = token_used
    if data:
        # 清理过大的数据（只保留摘要）
        if status == "completed" and isinstance(data, dict):
            message["data"] = _summarize_results(data)
        else:
            message["data"] = data

    await ws_manager.send_to_user(user_id, message)
    logger.info(
        "分析状态通知推送: user_id=%d, resume_id=%d, status=%s, tokens=%d",
        user_id,
        resume_id,
        status,
        token_used,
    )


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
