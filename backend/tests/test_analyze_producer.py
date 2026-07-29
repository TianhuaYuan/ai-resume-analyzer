"""Tests for resume analyze producer with RabbitMQ integration.

RED-GREEN-REFACTOR:
1. RED: Producer references rabbitmq_client — test will fail until implemented
2. GREEN: Update producer to use rabbitmq_client
3. REFACTOR: Clean up
"""

from unittest.mock import AsyncMock, patch

import pytest


class TestAnalyzeProducer:
    """简历分析生产者测试。"""

    async def test_publish_via_rabbitmq_success(self):
        """RabbitMQ 发送成功时返回 True。"""
        with (
            patch("services.resume_analyze_producer.settings") as mock_settings,
            patch("services.resume_analyze_producer.rabbitmq_client") as mock_rmq,
        ):
            mock_settings.RABBITMQ_ENABLED = True
            mock_rmq.send_message = AsyncMock(return_value=True)

            from services.resume_analyze_producer import publish_analyze_task
            result = await publish_analyze_task(
                resume_id=1, user_id=42, filename="test.pdf"
            )

            assert result is True
            mock_rmq.send_message.assert_called_once()

    async def test_publish_via_rabbitmq_fallback_to_sync(self):
        """MQ 发送失败时降级为同步执行。"""
        with (
            patch("services.resume_analyze_producer.settings") as mock_settings,
            patch("services.resume_analyze_producer.rabbitmq_client") as mock_rmq,
            patch(
                "services.resume_analyze_consumer.process_analyze_task",
                new_callable=AsyncMock,
            ) as mock_process,
        ):
            mock_settings.RABBITMQ_ENABLED = True
            mock_rmq.send_message = AsyncMock(return_value=False)

            from services.resume_analyze_producer import publish_analyze_task
            result = await publish_analyze_task(
                resume_id=1, user_id=42, filename="test.pdf"
            )

            assert result is True
            mock_rmq.send_message.assert_called_once()
            mock_process.assert_called_once()

    async def test_publish_disabled_direct_sync(self):
        """RABBITMQ_ENABLED=False 时直接同步执行。"""
        with (
            patch("services.resume_analyze_producer.settings") as mock_settings,
            patch(
                "services.resume_analyze_consumer.process_analyze_task",
                new_callable=AsyncMock,
            ) as mock_process,
        ):
            mock_settings.RABBITMQ_ENABLED = False

            from services.resume_analyze_producer import publish_analyze_task
            result = await publish_analyze_task(
                resume_id=1, user_id=42, filename="test.pdf"
            )

            assert result is True
            mock_process.assert_called_once()

    async def test_publish_sync_failure(self):
        """同步执行失败时返回 False。"""
        with (
            patch("services.resume_analyze_producer.settings") as mock_settings,
            patch("services.resume_analyze_producer.rabbitmq_client") as mock_rmq,
            patch(
                "services.resume_analyze_consumer.process_analyze_task",
                new_callable=AsyncMock,
            ) as mock_process,
        ):
            mock_settings.RABBITMQ_ENABLED = True
            mock_rmq.send_message = AsyncMock(return_value=False)
            mock_process.side_effect = RuntimeError("Analysis crashed")

            from services.resume_analyze_producer import publish_analyze_task
            result = await publish_analyze_task(
                resume_id=1, user_id=42, filename="test.pdf"
            )

            assert result is False
