"""
阶段2 / N1 测试（两部分）：

2.5  Client 双重检查锁（double-checked locking）
    - 并发调用 get_mcp_client 仅创建一次客户端
    - _client_lock 为模块级 asyncio.Lock
    - close 后再次获取得到新实例

2.6  MCP 工具加超时
    - mcp_client 真实 httpx 客户端使用 httpx.Timeout(30, connect=10)
    - 三个工具模块的 MCP_HTTP_TIMEOUT 常量与之一致（对齐阶段1）

运行: python -m pytest tests/test_mcp_client_locks.py -v
"""
import asyncio

import httpx
import pytest
from unittest.mock import patch

from mcp_client import client as client_mod
from mcp_client.client import (
    get_mcp_client,
    close_mcp_client,
    _client_lock,
    _DEFAULT_TIMEOUT,
)


def _as_tuple(t: httpx.Timeout):
    return (t.read, t.write, t.connect, t.pool)


# ── 2.5 双重检查锁 ─────────────────────────────────────

@pytest.mark.asyncio
async def test_double_checked_lock_single_creation():
    """并发获取客户端时仅创建一次（防止重复创建）。"""
    client_mod._client_instance = None
    created = []
    orig = client_mod.MCPClient

    def _spy(*a, **k):
        created.append(1)
        return orig(*a, **k)

    with patch.object(client_mod, "MCPClient", side_effect=_spy):
        instances = await asyncio.gather(*[get_mcp_client() for _ in range(20)])

    assert len(created) == 1, "并发下不应多次创建客户端"
    assert all(i is instances[0] for i in instances)
    client_mod._client_instance = None


def test_lock_is_module_level_asyncio_lock():
    """_client_lock 是模块级 asyncio.Lock（消除惰性创建竞态）。"""
    assert isinstance(_client_lock, asyncio.Lock)


@pytest.mark.asyncio
async def test_close_then_get_creates_new():
    """close 后再次获取得到新实例。"""
    client_mod._client_instance = None
    a = await get_mcp_client()
    await close_mcp_client()
    b = await get_mcp_client()
    assert a is not b
    client_mod._client_instance = None


# ── 2.6 MCP 工具加超时 ─────────────────────────────────

def test_client_default_timeout_is_httpx_timeout():
    """mcp_client 的默认超时应为 httpx.Timeout(30, connect=10)。"""
    expected = httpx.Timeout(30, connect=10)
    assert _as_tuple(_DEFAULT_TIMEOUT) == _as_tuple(expected)


def test_tool_timeout_constants_align():
    """三个工具模块的 MCP_HTTP_TIMEOUT 与 httpx.Timeout(30, connect=10) 一致。"""
    from mcp_server.tools.generate import MCP_HTTP_TIMEOUT as g
    from mcp_server.tools.rewrite import MCP_HTTP_TIMEOUT as r
    from mcp_server.tools.rerank import MCP_HTTP_TIMEOUT as re

    expected = _as_tuple(httpx.Timeout(30, connect=10))
    assert _as_tuple(g) == expected
    assert _as_tuple(r) == expected
    assert _as_tuple(re) == expected
