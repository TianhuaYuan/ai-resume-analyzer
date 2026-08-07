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
        # P2-7：优先复用 Trace 中间件已生成的 trace_id（中间件反序包裹，Trace 在
        # 外层先执行）。客户端不带 X-Request-ID 时，若各自 uuid4() 会产生
        # request_id != trace_id，破坏全链路对账。以 trace_id 为权威源，
        # request_id 跟随，二者恒一致。
        from core.trace import get_trace_id

        trace_id = get_trace_id()
        if trace_id and trace_id != "-":
            rid = trace_id
        else:
            rid = request.headers.get(HEADER_NAME) or str(uuid4())
        token = _request_id_ctx.set(rid)

        try:
            response = await call_next(request)
            response.headers[HEADER_NAME] = rid
            return response
        finally:
            _request_id_ctx.reset(token)
