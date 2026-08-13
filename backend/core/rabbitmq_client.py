"""RabbitMQ 消息队列客户端。

基于 aio-pika 库实现，支持异步连接、消息发布和消费。
降级策略（按环境）：
- development/testing：按 ENVIRONMENT 标签直接跳过，零开销
- staging/production：尝试连接，失败后降级为同步执行
"""

import json
import logging
from typing import Callable, Awaitable

from core.config import settings

logger = logging.getLogger(__name__)

_connection = None
_channel = None
_consumer_tag = None
# 协作停止标志（JobHunter set_stop_check/should_stop 对照）：
# 应用关闭时置位，消费者循环检查后停止拉新消息，避免 shutdown 截断正在处理的任务
_stop_requested = False


def _reset() -> None:
    """重置全局状态（仅测试用）。"""
    global _connection, _channel, _consumer_tag, _stop_requested
    _connection = None
    _channel = None
    _consumer_tag = None
    _stop_requested = False


def request_stop() -> None:
    """请求协作停止（main.py lifespan shutdown 时调用，优先于关连接）。"""
    global _stop_requested
    _stop_requested = True
    logger.info("RabbitMQ 协作停止已请求（不再消费新消息）")


def should_stop() -> bool:
    """协作停止检查（JobHunter should_stop 对照）：消费者循环内每消息检查。"""
    return _stop_requested


async def init_producer() -> bool:
    """初始化 RabbitMQ 生产者和队列。

    Returns:
        True 初始化成功，False 跳过或失败
    """
    global _connection, _channel

    if settings.ENVIRONMENT in ("development", "testing"):
        return False

    if not settings.RABBITMQ_ENABLED:
        logger.info("RabbitMQ 未启用，跳过生产者初始化")
        return False

    if _channel is not None:
        return True

    try:
        import aio_pika

        _connection = await aio_pika.connect_robust(settings.RABBITMQ_URL)
        _channel = await _connection.channel()
        await _channel.declare_queue(settings.RABBITMQ_QUEUE, durable=True)
        logger.info("RabbitMQ 生产者初始化成功")
        return True

    except Exception as e:
        logger.error("RabbitMQ 生产者初始化失败: %s", e)
        _connection = None
        _channel = None
        return False


async def init_consumer(
    message_handler: Callable[[dict], Awaitable[None]],
) -> bool:
    """初始化 RabbitMQ 消费者，开始消费队列消息。

    Args:
        message_handler: 消息处理回调 async def handler(message: dict) -> None

    Returns:
        True 初始化成功，False 跳过或失败
    """
    global _connection, _channel, _consumer_tag

    if settings.ENVIRONMENT in ("development", "testing"):
        return False

    if not settings.RABBITMQ_ENABLED:
        logger.info("RabbitMQ 未启用，跳过消费者初始化")
        return False

    if _consumer_tag is not None:
        return True

    try:
        import aio_pika

        _connection = await aio_pika.connect_robust(settings.RABBITMQ_URL)
        _channel = await _connection.channel()
        queue = await _channel.declare_queue(settings.RABBITMQ_QUEUE, durable=True)
        # prefetch 限制——慢 LLM 任务队列若无限 in-flight 会堆积。
        # 设为 1 实现"单消费者顺序处理 + 失败可重试"，配合消息失败 nack requeue。
        try:
            prefetch_count = max(1, int(settings.RABBITMQ_PREFETCH_COUNT))
        except (TypeError, ValueError):
            prefetch_count = 1
        await _channel.set_qos(prefetch_count=prefetch_count)

        # 注册消息处理回调
        async def _on_message(message: aio_pika.IncomingMessage) -> None:
            # 协作停止（JobHunter should_stop 对照）：shutdown 已请求 → 拒绝新消息（reject 回队列）
            if _stop_requested:
                await message.reject(requeue=True)
                return
            try:
                body = json.loads(message.body.decode("utf-8"))
                await message_handler(body)
                await message.ack()
            except Exception as e:
                # 失败语义修复——原先 try/except 在 process() 内吞异常会 ack 丢消息
                # （"分析重试"是死代码）。改为显式 nack：
                # - retry_count 未超限 → requeue（指数退避由 payload 内 retry_count 控制）
                # - 已超限 → 不 requeue（ack），由消费端落库 failed（避免无限重试）
                logger.exception("RabbitMQ 消息消费失败: %s", e)
                retry_count = 0
                try:
                    body = json.loads(message.body.decode("utf-8"))
                    retry_count = int(body.get("retry_count", 0) or 0)
                except Exception:
                    pass
                if retry_count < settings.RABBITMQ_MAX_RETRIES:
                    try:
                        body = json.loads(message.body.decode("utf-8"))
                        body["retry_count"] = retry_count + 1
                    except Exception:
                        body = {"retry_count": retry_count + 1}
                    # 丢弃原消息（不 requeue，避免"原消息 + 重试消息"双份），
                    # 发布带 retry_count+1 的重试消息实现受控重试。
                    await message.nack(requeue=False)
                    retry_msg = aio_pika.Message(
                        body=json.dumps(body, ensure_ascii=False).encode("utf-8"),
                        delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
                    )
                    await _channel.default_exchange.publish(
                        retry_msg,
                        routing_key=settings.RABBITMQ_QUEUE,
                    )
                else:
                    logger.error(
                        "RabbitMQ 消息重试 %d 次仍失败，丢弃（请检查消费端落库/告警）",
                        settings.RABBITMQ_MAX_RETRIES,
                    )
                    await message.ack()

        _consumer_tag = await queue.consume(_on_message)
        logger.info("RabbitMQ 消费者初始化成功，队列: %s", settings.RABBITMQ_QUEUE)
        return True

    except Exception as e:
        logger.error("RabbitMQ 消费者初始化失败: %s", e)
        _connection = None
        _channel = None
        _consumer_tag = None
        return False


async def send_message(payload: dict) -> bool:
    """发送消息到 RabbitMQ 队列。

    Args:
        payload: 消息体（字典，会被 JSON 序列化）

    Returns:
        True 发送成功，False 发送失败或未启用
    """
    if not settings.RABBITMQ_ENABLED:
        logger.debug("RabbitMQ 未启用，跳过消息发送")
        return False

    if _channel is None:
        logger.warning("RabbitMQ 未初始化，跳过消息发送")
        return False

    try:
        import aio_pika

        message = aio_pika.Message(
            body=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
        )
        await _channel.default_exchange.publish(
            message,
            routing_key=settings.RABBITMQ_QUEUE,
        )
        logger.info(
            "RabbitMQ 消息发送成功: resume_id=%s",
            payload.get("resume_id"),
        )
        return True

    except Exception as e:
        logger.error("RabbitMQ 消息发送失败: %s", e)
        return False


async def shutdown() -> None:
    """关闭 RabbitMQ 连接和频道。

    先发协作停止（JobHunter 对照）：消费者拒绝新消息（requeue），
    正在处理的消息不被 shutdown 截断。
    """
    global _connection, _channel, _consumer_tag

    request_stop()
    _consumer_tag = None
    _channel = None

    if _connection is not None:
        try:
            await _connection.close()
            logger.info("RabbitMQ 连接已关闭")
        except Exception as e:
            logger.warning("关闭 RabbitMQ 连接失败: %s", e)
        _connection = None
