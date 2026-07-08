"""
MCP Client 单元测试。

测试 MCPClient 的连接、工具调用、资源读取、错误处理。
全部 mock HTTP 调用，不依赖真实 MCP Server。
运行: python -m pytest tests/test_mcp_client.py -v
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from mcp_client.client import MCPClient, MCPClientError, get_mcp_client, close_mcp_client


# ── MCPClient 基础测试 ─────────────────────────────────────

class TestMCPClientInit:
    """MCPClient 初始化测试。"""

    def test_default_url(self):
        client = MCPClient()
        assert client.base_url == "http://127.0.0.1:8000/mcp"

    def test_custom_url(self):
        client = MCPClient(base_url="http://example.com/mcp")
        assert client.base_url == "http://example.com/mcp"

    def test_trailing_slash_stripped(self):
        client = MCPClient(base_url="http://example.com/mcp/")
        assert client.base_url == "http://example.com/mcp"

    def test_token_stored(self):
        client = MCPClient(token="test-token")
        assert client.token == "test-token"


class TestMCPClientConnect:
    """MCPClient 连接测试。"""

    @pytest.mark.asyncio
    async def test_connect_creates_httpx_client(self):
        client = MCPClient(base_url="http://test/mcp", token="tok")
        await client.connect()
        assert client._client is not None
        await client.disconnect()

    @pytest.mark.asyncio
    async def test_connect_idempotent(self):
        client = MCPClient()
        await client.connect()
        first = client._client
        await client.connect()
        assert client._client is first
        await client.disconnect()

    @pytest.mark.asyncio
    async def test_disconnect(self):
        client = MCPClient()
        await client.connect()
        await client.disconnect()
        assert client._client is None


class TestMCPClientCallTool:
    """MCPClient.call_tool 测试。"""

    @pytest.mark.asyncio
    async def test_call_tool_success(self):
        """正常调用返回结果。"""
        client = MCPClient(base_url="http://test/mcp")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "application/json"}
        mock_response.json.return_value = {
            "jsonrpc": "2.0",
            "id": "1",
            "result": {
                "content": [{"type": "text", "text": '{"status": "ok"}'}],
            },
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.aclose = AsyncMock()
        client._client = mock_client

        result = await client.call_tool("test_tool", {"arg": "value"})

        assert result == {"content": [{"type": "text", "text": '{"status": "ok"}'}]}
        mock_client.post.assert_called_once()

        # 验证 JSON-RPC 请求格式
        call_args = mock_client.post.call_args
        payload = call_args[1]["json"] if "json" in call_args[1] else call_args[0][1]
        assert payload["jsonrpc"] == "2.0"
        assert payload["method"] == "tools/call"
        assert payload["params"]["name"] == "test_tool"
        assert payload["params"]["arguments"] == {"arg": "value"}

    @pytest.mark.asyncio
    async def test_call_tool_mcp_error(self):
        """MCP 返回错误时抛出 MCPClientError。"""
        client = MCPClient()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "application/json"}
        mock_response.json.return_value = {
            "jsonrpc": "2.0",
            "id": "1",
            "error": {"code": -32601, "message": "Tool not found"},
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        client._client = mock_client

        with pytest.raises(MCPClientError, match="Tool not found"):
            await client.call_tool("nonexistent_tool", {})

    @pytest.mark.asyncio
    async def test_call_tool_http_error(self):
        """HTTP 错误时抛出 MCPClientError。"""
        import httpx

        client = MCPClient()
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"
        http_error = httpx.HTTPStatusError(
            "500 Server Error",
            request=MagicMock(),
            response=mock_response,
        )

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=http_error)
        client._client = mock_client

        with pytest.raises(MCPClientError, match="500"):
            await client.call_tool("test_tool", {})

    @pytest.mark.asyncio
    async def test_call_tool_connection_error(self):
        """连接错误时抛出 MCPClientError。"""
        import httpx

        client = MCPClient()
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))
        client._client = mock_client

        with pytest.raises(MCPClientError, match="Connection error"):
            await client.call_tool("test_tool", {})

    @pytest.mark.asyncio
    async def test_call_tool_parses_sse_response(self):
        """SSE 响应正确解析。"""
        client = MCPClient()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "text/event-stream"}

        async def mock_aiter_lines():
            yield 'data: {"jsonrpc":"2.0","id":"1","result":{"content":[{"type":"text","text":"{\\"ok\\":true}"}]}}'
            yield ""

        mock_response.aiter_lines = mock_aiter_lines
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        client._client = mock_client

        result = await client.call_tool("test_tool", {})
        assert "content" in result


class TestMCPClientReadResource:
    """MCPClient.read_resource 测试。"""

    @pytest.mark.asyncio
    async def test_read_resource_success(self):
        client = MCPClient()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "application/json"}
        mock_response.json.return_value = {
            "jsonrpc": "2.0",
            "id": "1",
            "result": {
                "contents": [{"uri": "resume://list", "text": '[{"id": 1}]'}],
            },
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        client._client = mock_client

        content = await client.read_resource("resume://list")
        assert content == '[{"id": 1}]'

    @pytest.mark.asyncio
    async def test_read_resource_empty(self):
        client = MCPClient()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "application/json"}
        mock_response.json.return_value = {
            "jsonrpc": "2.0",
            "id": "1",
            "result": {"contents": []},
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        client._client = mock_client

        content = await client.read_resource("resume://empty")
        # 空 contents 时返回 JSON 序列化的完整 result
        assert "contents" in content


# ── 单例管理测试 ───────────────────────────────────────────

class TestMCPSingleton:
    """get_mcp_client / close_mcp_client 测试。"""

    @pytest.mark.asyncio
    async def test_get_creates_singleton(self):
        from mcp_client import client as client_mod

        client_mod._client_instance = None
        c1 = await get_mcp_client()
        c2 = await get_mcp_client()
        assert c1 is c2
        client_mod._client_instance = None

    @pytest.mark.asyncio
    async def test_close_clears_singleton(self):
        from mcp_client import client as client_mod

        client_mod._client_instance = await get_mcp_client()
        await close_mcp_client()
        assert client_mod._client_instance is None


# ── _parse_tool_result 测试 ────────────────────────────────

class TestParseToolResult:
    """_parse_tool_result 辅助函数测试。"""

    def test_parse_normal(self):
        from mcp_client.tools import _parse_tool_result

        result = {
            "content": [{"type": "text", "text": '{"key": "value"}'}],
        }
        parsed = _parse_tool_result(result)
        assert parsed == {"key": "value"}

    def test_parse_list(self):
        from mcp_client.tools import _parse_tool_result

        result = {
            "content": [{"type": "text", "text": '[{"a": 1}, {"b": 2}]'}],
        }
        parsed = _parse_tool_result(result)
        assert parsed == [{"a": 1}, {"b": 2}]

    def test_parse_empty_content(self):
        from mcp_client.tools import _parse_tool_result

        parsed = _parse_tool_result({"content": []})
        assert parsed == {}

    def test_parse_non_json_text(self):
        from mcp_client.tools import _parse_tool_result

        result = {
            "content": [{"type": "text", "text": "not json"}],
        }
        parsed = _parse_tool_result(result)
        assert parsed == {"raw": "not json"}

    def test_parse_no_result(self):
        from mcp_client.tools import _parse_tool_result

        parsed = _parse_tool_result({})
        assert parsed == {}
