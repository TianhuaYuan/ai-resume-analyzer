"""简历解析任务消费者。

由 RabbitMQ 消费者触发，执行流程：
1. 调 process_resume_background（三阶段解析，内部更新 parse_progress + WebSocket 推送）
2. 失败且未达最大重试次数 → 重新入队（retry_count + 1）
3. 超过最大重试次数 → 记错误日志（DB 已由 process_resume_background 标记 failed，
   用户可手动重试 retry 端点）

与 resume_analyze_consumer 的区别：解析任务不涉及分布式锁/Redis 幂等/token 限额，
重试语义由消息队列入队实现（而非进程内循环），保证重启后任务不丢。
"""

import logging

from sqlalchemy import select

from core import rabbitmq_client
from core.database import AsyncSessionLocal
from models.resume import Resume

logger = logging.getLogger(__name__)

# 最大重试次数（达到后不再重新入队，DB 标记 failed，等待用户手动重试）
MAX_PARSE_RETRY = 2


async def _resume_exists(resume_id: int) -> bool:
    """查询简历是否仍存在（用户删除后丢弃僵尸任务，避免解析/重试空转）。

    DB 查询失败时放行（返回 True），交给 process_resume_background 兜底，
    不因校验本身阻断任务。
    """
    try:
        async with AsyncSessionLocal() as db:
            row = await db.execute(select(Resume.id).where(Resume.id == resume_id))
            return row.scalar_one_or_none() is not None
    except Exception:
        logger.warning("简历存在性校验失败，放行任务: resume_id=%d", resume_id, exc_info=True)
        return True


async def process_parse_task(payload: dict) -> None:
    """处理单个解析任务。

    此函数可被：
    - RabbitMQ 消费者直接调用（经 main.py 的 task 分发 handler）
    - 直接调用（测试 / 手动触发）

    Args:
        payload: 消息体，包含 resume_id, user_id, file_path, retry_count
    """
    resume_id = payload.get("resume_id")
    user_id = payload.get("user_id", 0)
    file_path = payload.get("file_path")
    retry_count = payload.get("retry_count", 0)

    if resume_id is None or not file_path:
        logger.error("解析任务缺少必要参数: %s", payload)
        return

    # 用户可能在任务排队期间删除了简历 → 丢弃僵尸任务（不触发解析、不重试）
    if not await _resume_exists(resume_id):
        logger.warning("解析任务对应简历已删除，丢弃: resume_id=%d", resume_id)
        return

    from services import resume_service

    ok = await resume_service.process_resume_background(
        resume_id, file_path, user_id
    )
    if ok:
        return

    # 处理失败：未达上限 → 重新入队重试
    if retry_count < MAX_PARSE_RETRY:
        retry_payload = {**payload, "retry_count": retry_count + 1}
        re_sent = await rabbitmq_client.send_message(retry_payload)
        if re_sent:
            logger.warning(
                "解析失败，已重新入队重试: resume_id=%d, retry=%d/%d",
                resume_id, retry_count + 1, MAX_PARSE_RETRY,
            )
        else:
            logger.warning(
                "解析失败且重试入队失败（MQ 不可用），不再重试: resume_id=%d",
                resume_id,
            )
    else:
        logger.error(
            "解析失败已达最大重试次数 %d，标记 failed 等待手动重试: resume_id=%d",
            MAX_PARSE_RETRY, resume_id,
        )
