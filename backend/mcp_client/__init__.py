"""MCP Client — 通过标准 MCP 协议调用工具，供 Agentic RAG Agent 使用。"""

from mcp_client.client import MCPClient, get_mcp_client, close_mcp_client

__all__ = ["MCPClient", "get_mcp_client", "close_mcp_client"]
