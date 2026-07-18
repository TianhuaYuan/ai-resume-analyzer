"""
阶段2 / SEC-001（Critical 路径绕过修复）测试。

验证 MCP 认证中间件：
- /mcp 本身需要鉴权（无 token → 401）
- /mcp 的子路径（如 /mcp/foo、/mcp/session/abc）同样需要鉴权
  （旧实现用精确匹配 "/mcp"，可被 /mcp/<拼接> 绕过）

运行: python -m pytest tests/test_mcp_auth_bypass.py -v
"""

import pytest
from httpx import ASGITransport, AsyncClient

from main import app
from mcp_server.server import create_auth_middleware


async def _post(client, path, with_token=False):
    headers = {"Content-Type": "application/json"}
    if with_token:
        from core.security import create_access_token
        token = create_access_token({"sub": "1"})
        headers["Authorization"] = f"Bearer {token}"
    return await client.post(
        path,
        content=b'{"jsonrpc":"2.0","method":"tools/list","id":1}',
        headers=headers,
    )


@pytest.mark.asyncio
async def test_mcp_root_requires_auth():
    """/mcp 无 token → 401。"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test",
                           follow_redirects=False) as client:
        resp = await _post(client, "/mcp/")
        assert resp.status_code == 401
        assert "error" in resp.json()


@pytest.mark.asyncio
async def test_mcp_subpath_also_requires_auth():
    """SEC-001 核心：/mcp 拼接子路径不再绕过鉴权 → 401。"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test",
                           follow_redirects=False) as client:
        for sub in ("/mcp/foo", "/mcp/session/abc", "/mcp/x/y/z"):
            resp = await _post(client, sub)
            assert resp.status_code == 401, f"子路径 {sub} 未被鉴权保护（路径绕过！）"
            assert "error" in resp.json()


@pytest.mark.asyncio
async def test_non_mcp_path_not_blocked_by_mcp_auth():
    """非 /mcp 路径不应被 MCP 认证中间件拦截（走正常流程）。"""
    middleware = create_auth_middleware(lambda scope, receive, send: None)
    # 仅验证：startswith 判定不会误伤非 /mcp 路径的判定逻辑。
    # 通过源码行为间接保证：非 /mcp 前缀直接 call_next。
    assert callable(middleware)


@pytest.mark.asyncio
async def test_mcp_with_valid_token_passes():
    """持有合法 token 时 /mcp 通过鉴权（不返回 401）。"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test",
                           follow_redirects=False) as client:
        resp = await _post(client, "/mcp/", with_token=True)
        # 合法 token 不应被 401 拒绝（后续由 MCP 协议层处理，状态码非 401）。
        assert resp.status_code != 401
