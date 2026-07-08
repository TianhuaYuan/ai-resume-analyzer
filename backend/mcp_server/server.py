"""MCP Server：FastMCP 实例 + JWT 认证中间件。"""

import contextvars
import logging

from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)

_current_user_id: contextvars.ContextVar[int] = contextvars.ContextVar(
    "mcp_current_user_id",
)


def get_current_user_id() -> int:
    return _current_user_id.get()


mcp = FastMCP(
    name="ai-resume-analyzer",
    instructions=(
        "你是一个简历分析助手。你可以通过以下工具与简历知识库交互：\n"
        "- search_knowledge_base：在简历知识库中搜索相关信息\n"
        "- analyze_resume：分析简历内容，提取关键信息\n"
        "- rewrite_query：改写用户查询以提高检索效果\n"
        "每个工具都需要 resume_id 参数来指定要操作的简历。"
    ),
)


def _register_handlers() -> None:
    from mcp_server.tools import search, analyze, rewrite, rerank, generate  # noqa: F401
    from mcp_server.resources import resumes, history  # noqa: F401

    logger.info("MCP tools and resources registered")


def create_auth_middleware(app):
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.requests import Request
    from starlette.responses import JSONResponse

    from core.security import decode_token

    class MCPAuthMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next):
            path = request.url.path.rstrip("/")
            if path not in ("/mcp",):
                return await call_next(request)

            auth_header = request.headers.get("authorization", "")
            if not auth_header.startswith("Bearer "):
                return JSONResponse(
                    {"error": "Missing or invalid Authorization header"},
                    status_code=401,
                )

            token = auth_header[7:]
            payload = decode_token(token)
            if payload is None:
                return JSONResponse(
                    {"error": "Invalid or expired token"},
                    status_code=401,
                )

            if payload.get("type") != "access":
                return JSONResponse(
                    {"error": "Invalid token type"},
                    status_code=401,
                )

            user_id_str = payload.get("sub")
            if user_id_str is None:
                return JSONResponse(
                    {"error": "Invalid token payload"},
                    status_code=401,
                )

            try:
                user_id = int(user_id_str)
            except (ValueError, TypeError):
                return JSONResponse(
                    {"error": "Invalid token payload"},
                    status_code=401,
                )

            token_obj = _current_user_id.set(user_id)
            try:
                response = await call_next(request)
                return response
            finally:
                _current_user_id.reset(token_obj)

    return MCPAuthMiddleware(app)
