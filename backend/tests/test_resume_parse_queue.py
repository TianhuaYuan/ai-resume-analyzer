"""A1: 简历解析任务队列化单元测试。

覆盖：
- publish_parse_task：MQ 启用成功入队 / MQ 未启用降级 create_task / 非协程防御
- process_parse_task：成功不重试 / 失败按 retry_count 重试入队 / 超上限停止 / 缺参直接返回
"""

from unittest.mock import AsyncMock, patch

import pytest

from services.resume_parse_consumer import MAX_PARSE_RETRY, process_parse_task
from services.resume_parse_producer import publish_parse_task


# ═══════════════════════════════════════════════════════════
# publish_parse_task（生产者）
# ═══════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_publish_parse_task_mq_disabled_falls_back_to_background(monkeypatch):
    """MQ 未启用（RABBITMQ_ENABLED=False）→ 降级 asyncio.create_task 调用解析函数。"""
    monkeypatch.setattr("core.config.settings.RABBITMQ_ENABLED", False)

    with patch(
        "services.resume_service.process_resume_background",
        new_callable=AsyncMock,
    ) as mock_bg:
        ok = await publish_parse_task(resume_id=1, user_id=2, file_path="/tmp/a.pdf")

    assert ok is True
    mock_bg.assert_awaited_once_with(1, "/tmp/a.pdf", 2)


@pytest.mark.asyncio
async def test_publish_parse_task_mq_success_skips_background(monkeypatch):
    """MQ 启用且发送成功 → 入队，不再调度进程内任务。"""
    monkeypatch.setattr("core.config.settings.RABBITMQ_ENABLED", True)

    with patch("core.rabbitmq_client.send_message", new_callable=AsyncMock, return_value=True) as mock_send, \
         patch("services.resume_service.process_resume_background", new_callable=AsyncMock) as mock_bg:
        ok = await publish_parse_task(resume_id=1, user_id=2, file_path="/tmp/a.pdf")

    assert ok is True
    mock_send.assert_awaited_once()
    sent_payload = mock_send.await_args.args[0]
    assert sent_payload["task"] == "resume_parse"
    assert sent_payload["resume_id"] == 1
    assert sent_payload["user_id"] == 2
    assert sent_payload["file_path"] == "/tmp/a.pdf"
    assert sent_payload["retry_count"] == 0
    mock_bg.assert_not_awaited()


@pytest.mark.asyncio
async def test_publish_parse_task_mq_send_failure_falls_back(monkeypatch):
    """MQ 启用但发送失败 → 降级进程内后台执行。"""
    monkeypatch.setattr("core.config.settings.RABBITMQ_ENABLED", True)

    with patch("core.rabbitmq_client.send_message", new_callable=AsyncMock, return_value=False), \
         patch("services.resume_service.process_resume_background", new_callable=AsyncMock) as mock_bg:
        ok = await publish_parse_task(resume_id=1, user_id=2, file_path="/tmp/a.pdf")

    assert ok is True
    mock_bg.assert_awaited_once()


@pytest.mark.asyncio
async def test_publish_parse_task_sync_replace_no_crash(monkeypatch):
    """解析函数被替换为同步函数（测试替身）→ 不调度、不崩溃、返回 True。"""
    monkeypatch.setattr("core.config.settings.RABBITMQ_ENABLED", False)

    with patch(
        "services.resume_service.process_resume_background",
        lambda *a, **k: None,  # 同步替身（与 test_production_hardening 的 monkeypatch 一致）
    ):
        ok = await publish_parse_task(resume_id=1, user_id=2, file_path="/tmp/a.pdf")

    assert ok is True


# ═══════════════════════════════════════════════════════════
# process_parse_task（消费者）
# ═══════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_process_parse_task_success_no_retry():
    """解析成功 → 不重新入队。"""
    with patch(
        "services.resume_service.process_resume_background",
        new_callable=AsyncMock,
        return_value=True,
    ) as mock_bg, \
         patch("core.rabbitmq_client.send_message", new_callable=AsyncMock) as mock_send, \
         patch(
             "services.resume_parse_consumer._resume_exists",
             new_callable=AsyncMock,
             return_value=True,
         ) as mock_exists:
        await process_parse_task({
            "task": "resume_parse",
            "resume_id": 1,
            "user_id": 2,
            "file_path": "/tmp/a.pdf",
            "retry_count": 0,
        })

    mock_exists.assert_awaited_once_with(1)
    mock_bg.assert_awaited_once_with(1, "/tmp/a.pdf", 2)
    mock_send.assert_not_awaited()


@pytest.mark.asyncio
async def test_process_parse_task_failure_requeues_with_increment():
    """解析失败且未达上限 → 重新入队，retry_count + 1。"""
    with patch(
        "services.resume_service.process_resume_background",
        new_callable=AsyncMock,
        return_value=False,
    ), \
         patch("core.rabbitmq_client.send_message", new_callable=AsyncMock, return_value=True) as mock_send, \
         patch(
             "services.resume_parse_consumer._resume_exists",
             new_callable=AsyncMock,
             return_value=True,
         ):
        await process_parse_task({
            "task": "resume_parse",
            "resume_id": 1,
            "user_id": 2,
            "file_path": "/tmp/a.pdf",
            "retry_count": 0,
        })

    mock_send.assert_awaited_once()
    retry_payload = mock_send.await_args.args[0]
    assert retry_payload["retry_count"] == 1


@pytest.mark.asyncio
async def test_process_parse_task_failure_max_retries_stops():
    """解析失败且已达最大重试次数 → 不再重新入队（DB 已标 failed，等待手动重试）。"""
    with patch(
        "services.resume_service.process_resume_background",
        new_callable=AsyncMock,
        return_value=False,
    ), \
         patch("core.rabbitmq_client.send_message", new_callable=AsyncMock) as mock_send, \
         patch(
             "services.resume_parse_consumer._resume_exists",
             new_callable=AsyncMock,
             return_value=True,
         ):
        await process_parse_task({
            "task": "resume_parse",
            "resume_id": 1,
            "user_id": 2,
            "file_path": "/tmp/a.pdf",
            "retry_count": MAX_PARSE_RETRY,
        })

    mock_send.assert_not_awaited()


@pytest.mark.asyncio
async def test_process_parse_task_failure_requeue_fails_stops():
    """解析失败、重试入队也失败（MQ 不可用）→ 不再重试。"""
    with patch(
        "services.resume_service.process_resume_background",
        new_callable=AsyncMock,
        return_value=False,
    ), \
         patch("core.rabbitmq_client.send_message", new_callable=AsyncMock, return_value=False) as mock_send, \
         patch(
             "services.resume_parse_consumer._resume_exists",
             new_callable=AsyncMock,
             return_value=True,
         ):
        await process_parse_task({
            "task": "resume_parse",
            "resume_id": 1,
            "user_id": 2,
            "file_path": "/tmp/a.pdf",
            "retry_count": 0,
        })

    mock_send.assert_awaited_once()  # 尝试了重发
    # 无异常抛出即可


@pytest.mark.asyncio
async def test_process_parse_task_missing_args_returns():
    """缺少必要参数（resume_id / file_path）→ 直接返回，不调用解析函数。"""
    with patch(
        "services.resume_service.process_resume_background",
        new_callable=AsyncMock,
    ) as mock_bg:
        await process_parse_task({"task": "resume_parse", "resume_id": None})
        await process_parse_task({"task": "resume_parse", "file_path": ""})

    mock_bg.assert_not_awaited()


@pytest.mark.asyncio
async def test_process_parse_task_resume_deleted_discards():
    """简历已删除 → 丢弃僵尸任务，不调用解析函数、不重试入队。"""
    with patch(
        "services.resume_parse_consumer._resume_exists",
        new_callable=AsyncMock,
        return_value=False,
    ) as mock_exists, \
         patch(
             "services.resume_service.process_resume_background",
             new_callable=AsyncMock,
         ) as mock_bg, \
         patch("core.rabbitmq_client.send_message", new_callable=AsyncMock) as mock_send:
        await process_parse_task({
            "task": "resume_parse",
            "resume_id": 1,
            "user_id": 2,
            "file_path": "/tmp/a.pdf",
            "retry_count": 0,
        })

    mock_exists.assert_awaited_once_with(1)
    mock_bg.assert_not_awaited()
    mock_send.assert_not_awaited()
