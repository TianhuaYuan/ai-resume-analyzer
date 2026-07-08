"""MCP HTTP 传输层：FastMCP → ASGI 子应用，挂载到 FastAPI /mcp。"""

import logging

from mcp_server.server import create_auth_middleware, mcp

logger = logging.getLogger(__name__)

_app = None


def init_mcp_server():
    from mcp_server.server import _register_handlers

    _register_handlers()
    logger.info("MCP Server initialized")


class _MCPRootASGI:
    def __init__(self, mcp_asgi_app):
        self._mcp_app = mcp_asgi_app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            path = scope.get("path", "")
            if path in ("", "/"):
                scope = dict(scope)
                scope["path"] = "/mcp"
                scope["raw_path"] = b"/mcp"
        await self._mcp_app(scope, receive, send)


def get_mcp_app():
    global _app
    if _app is not None:
        return _app

    raw_app = mcp.streamable_http_app()
    auth_app = create_auth_middleware(raw_app)
    _app = _MCPRootASGI(auth_app)

    logger.info("MCP HTTP app created (streamable HTTP transport)")
    return _app


async def shutdown_mcp_server():
    try:
        await mcp.session_manager.close()
        logger.info("MCP Server shut down")
    except Exception as e:
        logger.warning("MCP shutdown error: %s", e)
