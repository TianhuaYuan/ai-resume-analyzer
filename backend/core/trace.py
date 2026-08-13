from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager, contextmanager
from contextvars import ContextVar
from uuid import uuid4

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from core.request_id import HEADER_NAME as REQUEST_ID_HEADER
from core.metrics import rag_step_duration, rag_step_errors

logger = logging.getLogger(__name__)

# 请求级 trace_id（与 X-Request-ID 同源，确保指标/日志/链路三者对齐）。
# 默认 "-" 表示"当前不在任何请求上下文内"，避免日志里出现空字段。
_trace_id_ctx: ContextVar[str] = ContextVar("trace_id", default="-")

# 回写给客户端的响应头；前端/网关排障时可原样带回运单号。
TRACE_HEADER = "X-Trace-ID"
def get_trace_id() -> str:
    """返回当前请求（或协程）的 trace_id；请求外返回 '-'。

    下游代码（LLM 装饰器、RAG 步骤、业务埋点）随时可调用，
    拿到与 X-Request-ID 完全一致的运单号用于日志关联。
    """
    return _trace_id_ctx.get()


class TraceMiddleware(BaseHTTPMiddleware):
    """把 X-Request-ID（或新生成 UUID）作为 trace_id 在请求上下文内透传。

    - 读取请求头 X-Request-ID 作为 trace_id（与 RequestIDMiddleware 对齐）。
    - 写入 contextvars，下游（LLM 调用 / RAG 步骤 / 业务埋点）可随时取用。
    - 在响应头回写 X-Trace-ID，方便前端 / 网关在出错时回带运单号。
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # 直接读请求头而非依赖顺序：即使中间件装配顺序变化也能拿到。
        trace_id = request.headers.get(REQUEST_ID_HEADER) or str(uuid4())
        token = _trace_id_ctx.set(trace_id)
        try:
            response = await call_next(request)
            response.headers[TRACE_HEADER] = trace_id
            return response
        finally:
            _trace_id_ctx.reset(token)


def install_trace_middleware(app) -> None:
    """在 FastAPI 应用上挂载 TraceMiddleware。"""
    app.add_middleware(TraceMiddleware)


# 日志关联：把 trace_id 注入每条日志，便于检索
class TraceIDFilter(logging.Filter):
    """为每条日志记录附加 `trace_id` 字段（默认 '-'）。"""
    def filter(self, record: logging.LogRecord) -> bool:
        record.trace_id = get_trace_id()
        return True

def install_trace_logging() -> None:
    """给根日志器及其 handler 安装 TraceIDFilter，使所有日志自动带 trace_id。 """
    root = logging.getLogger()
    root.addFilter(TraceIDFilter())
    for handler in root.handlers:
        handler.addFilter(TraceIDFilter())


# 非 HTTP 上下文（后台任务 / 异步 worker）手动绑定
def _make_trace_id(trace_id: str | None = None) -> tuple[str, ContextVar.Token]:
    """创建 trace_id 并设置到 contextvars，返回 (trace_id, token) 供调用方 reset。"""
    tid = trace_id or str(uuid4())
    token = _trace_id_ctx.set(tid)
    return tid, token


@contextmanager
def bind_trace_id(trace_id: str | None = None):
    """手动绑定一个 trace_id，用于后台任务等非 HTTP 请求上下文。"""
    tid, token = _make_trace_id(trace_id)
    try:
        yield tid
    finally:
        _trace_id_ctx.reset(token)


@asynccontextmanager
async def bind_trace_id_async(trace_id: str | None = None):
    """`bind_trace_id` 的 async 版本，用于 `async with` 场景。"""
    tid, token = _make_trace_id(trace_id)
    try:
        yield tid
    finally:
        _trace_id_ctx.reset(token)


class StepTimer:
    """RAG 全链路分步计时器：对每一步掐表，既记录 Prometheus 指标又给出可返回的分段耗时。"""

    def __init__(self) -> None:
        self.steps: dict[str, float] = {}
        self._start = time.perf_counter()

    async def run(self, step: str, awaitable):
        """计时执行一个协程；成功记录耗时，异常记错误计数并向上抛。"""
        start = time.perf_counter()
        try:
            result = await awaitable
            return result
        except Exception as exc:
            rag_step_errors.labels(step=step, error_type=type(exc).__name__).inc()
            raise
        finally:
            elapsed = time.perf_counter() - start
            self.steps[step] = elapsed
            rag_step_duration.labels(step=step).observe(elapsed)

    def log(self) -> None:
        """打印各分步耗时摘要（便于日志侧排障，与 Prometheus 指标互补）。"""
        total = time.perf_counter() - self._start
        breakdown = ", ".join(f"{k}={v * 1000:.1f}ms" for k, v in self.steps.items())
        logger.info("RAG pipeline timing: total=%.1fms | %s", total * 1000, breakdown)
