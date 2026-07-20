"""MCP 客户端：JSON-RPC 2.0 over HTTP，支持 JSON + SSE 双格式。"""

import asyncio
import json
import logging
import uuid

import httpx

logger = logging.getLogger(__name__)

_DEFAULT_BASE_URL = "http://127.0.0.1:8000/mcp"
# 2.6 N1：对外 HTTP 调用统一超时（对齐阶段1：30s 总时限 / 10s 连接）
_DEFAULT_TIMEOUT = httpx.Timeout(30, connect=10)


class MCPClientError(Exception):
    def __init__(self, message: str, code: int | None = None, data: str | None = None):
        super().__init__(message)
        self.code = code
        self.data = data


class MCPClient:
    def __init__(self, base_url: str = _DEFAULT_BASE_URL, token: str = ""):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self._client: httpx.AsyncClient | None = None

    async def connect(self) -> None:
        if self._client is not None:
            return
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            headers=headers,
            timeout=_DEFAULT_TIMEOUT,
        )
        logger.info("MCP client connected to %s", self.base_url)

    async def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            await self.connect()
        return self._client

    async def call_tool(self, tool_name: str, arguments: dict) -> dict:
        client = await self._ensure_client()
        request_id = str(uuid.uuid4())[:8]

        payload = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": arguments,
            },
        }

        logger.debug(
            "MCP call_tool: %s args=%s (id=%s)",
            tool_name,
            json.dumps(arguments, ensure_ascii=False)[:200],
            request_id,
        )

        try:
            response = await client.post("/", json=payload)
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise MCPClientError(
                f"HTTP {e.response.status_code}: {e.response.text[:200]}",
                code=e.response.status_code,
            ) from e
        except httpx.RequestError as e:
            raise MCPClientError(f"Connection error: {e}") from e

        content_type = response.headers.get("content-type", "")
        if "text/event-stream" in content_type:
            return await self._parse_sse_response(response, request_id)

        body = response.json()
        return self._extract_result(body, request_id)

    async def read_resource(self, uri: str) -> str:
        client = await self._ensure_client()
        request_id = str(uuid.uuid4())[:8]

        payload = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "resources/read",
            "params": {"uri": uri},
        }

        try:
            response = await client.post("/", json=payload)
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise MCPClientError(
                f"HTTP {e.response.status_code}: {e.response.text[:200]}",
                code=e.response.status_code,
            ) from e
        except httpx.RequestError as e:
            raise MCPClientError(f"Connection error: {e}") from e

        content_type = response.headers.get("content-type", "")
        if "text/event-stream" in content_type:
            result = await self._parse_sse_response(response, request_id)
        else:
            body = response.json()
            result = self._extract_result(body, request_id)

        contents = result.get("contents", [])
        if contents:
            return contents[0].get("text", "")
        return json.dumps(result, ensure_ascii=False)

    async def disconnect(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
            logger.info("MCP client disconnected")

    async def _parse_sse_response(
        self,
        response: httpx.Response,
        request_id: str,
    ) -> dict:
        last_data = None
        async for line in response.aiter_lines():
            if line.startswith("data: "):
                data_str = line[6:].strip()
                if data_str:
                    try:
                        last_data = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue

        if last_data is None:
            raise MCPClientError("No data received from SSE stream")
        return self._extract_result(last_data, request_id)

    @staticmethod
    def _extract_result(body: dict, request_id: str) -> dict:
        if "error" in body:
            error = body["error"]
            raise MCPClientError(
                f"MCP error {error.get('code', '?')}: {error.get('message', 'unknown')}",
                code=error.get("code"),
                data=error.get("data"),
            )

        result = body.get("result", {})
        return result


_client_instance: MCPClient | None = None
# 2.5 N1：模块级单例锁，避免惰性创建时的竞态；
# 配合下方 get_mcp_client 的双重检查锁（double-checked locking）防止并发重复创建。
_client_lock: asyncio.Lock = asyncio.Lock()


async def get_mcp_client(
    base_url: str = _DEFAULT_BASE_URL,
    token: str = "",
) -> MCPClient:
    global _client_instance
    # 第一次检查（无锁，快速路径）
    if _client_instance is not None:
        return _client_instance

    # 获取锁后进行第二次检查（双重检查锁核心）
    async with _client_lock:
        if _client_instance is not None:
            return _client_instance
        _client_instance = MCPClient(base_url=base_url, token=token)
        return _client_instance


async def close_mcp_client() -> None:
    global _client_instance
    if _client_instance is not None:
        await _client_instance.disconnect()
        _client_instance = None
