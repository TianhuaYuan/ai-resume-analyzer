"""P1-11: _get_http_client 并发安全测试。

原 bug: check-then-act 模式在多协程下可能创建多个 httpx 客户端实例。
修复: 加 asyncio.Lock 保证单例。
"""
import asyncio
from unittest.mock import MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_get_http_client_returns_same_instance():
    """多次调用应返回同一个客户端实例（单例）。"""
    import services.rag.retrieval as retrieval

    retrieval._http_client = None

    results = await asyncio.gather(
        *[retrieval._get_http_client() for _ in range(5)]
    )

    assert all(r is results[0] for r in results), "所有调用应返回同一个实例"


@pytest.mark.asyncio
async def test_get_http_client_uses_lock():
    """_get_http_client 应通过锁保护创建过程，避免 TOCTOU 竞态。"""
    import services.rag.retrieval as retrieval

    assert hasattr(retrieval, "_http_client_lock"), "应存在模块级锁 _http_client_lock"
    assert isinstance(retrieval._http_client_lock, asyncio.Lock)


@pytest.mark.asyncio
async def test_get_http_client_recreates_when_closed():
    """client 被关闭后再次调用应重建。"""
    import services.rag.retrieval as retrieval

    retrieval._http_client = None

    first = await retrieval._get_http_client()
    # 模拟 client 被关闭
    type(first).is_closed = property(lambda self: True)
    second = await retrieval._get_http_client()

    assert first is not second, "client 关闭后应重建"
