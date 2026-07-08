"""Request ID 中间件：自动生成 UUID4 + contextvars + 响应头。"""

from contextvars import ContextVar
from uuid import uuid4

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

_request_id_ctx: ContextVar[str] = ContextVar("request_id", default="-")

HEADER_NAME = "X-Request-ID"


def get_request_id() -> str:
    return _request_id_ctx.get()


class RequestIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        rid = request.headers.get(HEADER_NAME) or str(uuid4())
        token = _request_id_ctx.set(rid)

        try:
            response = await call_next(request)
            response.headers[HEADER_NAME] = rid
            return response
        finally:
            _request_id_ctx.reset(token)
