"""请求级 Trace 上下文透传（阶段10 / OBS 可观测性）。

⚠️ 接线位置（本阶段禁止修改 main.py，阶段9 独享其编辑权）：
   请在 main.py 现有的 `app.add_middleware(MetricsMiddleware)` 之后，追加一行：
       from core.trace import install_trace_middleware
       install_trace_middleware(app)
   本文件只提供安装函数 `install_trace_middleware(app)`，不在 main.py 中调用，
   由主流程（阶段9 完成后）统一接线，避免同文件并发编辑冲突。

生活化类比：
   把一次 HTTP 请求想象成一次"快递配送"，X-Request-ID 就是运单号。
   这个中间件做的事 = 给这次配送建一份"随单档案"(contextvars)。
   配送途中的每个环节（查库 / 调 LLM / RAG 检索 / 业务埋点）都把这个
   运单号写进自己的日志。事后你只要拿运单号，就能把整条链路串起来看，
   而不用在几十个服务里大海捞针。
   指标(metrics)看"整体快慢"，日志(logs)看"具体发生了什么"，
   trace 把两者用同一个运单号缝在一起 —— 这就是可观测性的三大支柱里
   的 "Trace（链路）"。
"""

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
        # 直接读请求头而非依赖顺序：即使中间件装配顺序变化也能拿到运单号。
        trace_id = request.headers.get(REQUEST_ID_HEADER) or str(uuid4())
        token = _trace_id_ctx.set(trace_id)
        try:
            response = await call_next(request)
            response.headers[TRACE_HEADER] = trace_id
            return response
        finally:
            _trace_id_ctx.reset(token)


def install_trace_middleware(app) -> None:
    """在 FastAPI 应用上挂载 TraceMiddleware。

    ⚠️ 仅提供安装函数，**不要在本阶段由本文件或 main.py 调用**。
    请在 main.py 现有的 `app.add_middleware(MetricsMiddleware)` 之后追加：
        install_trace_middleware(app)
    由主流程（阶段9 完成后）统一接线，避免与阶段9 对 main.py 的并发编辑冲突。
    """
    app.add_middleware(TraceMiddleware)


# ── 日志关联：把 trace_id 注入每条日志，便于按运单号检索 ──
class TraceIDFilter(logging.Filter):
    """为每条日志记录附加 `trace_id` 字段（默认 '-'，请求内为真实运单号）。

    用法：在日志格式串里使用 %(trace_id)s，例如：
        "%(asctime)s %(levelname)s [%(trace_id)s] %(name)s: %(message)s"
    """

    def filter(self, record: logging.LogRecord) -> bool:
        record.trace_id = get_trace_id()
        return True


def install_trace_logging() -> None:
    """给根日志器及其 handler 安装 TraceIDFilter，使所有日志自动带 trace_id。

    ⚠️ 同样**不在此阶段自动调用**，由主流程在 logging 初始化后统一接线：
        from core.trace import install_trace_logging
        install_trace_logging()
    调用方需在日志格式里使用 %(trace_id)s（见 TraceIDFilter 说明）。
    """
    root = logging.getLogger()
    root.addFilter(TraceIDFilter())
    for handler in root.handlers:
        handler.addFilter(TraceIDFilter())


# ── 非 HTTP 上下文（后台任务 / 异步 worker）手动绑定运单号 ──
@contextmanager
def bind_trace_id(trace_id: str | None = None):
    """手动绑定一个 trace_id，用于后台任务等非 HTTP 请求上下文。

    用法：
        with bind_trace_id():        # 自动生成
            do_background_work()
        with bind_trace_id("job-7"): # 指定运单号
            do_background_work()
    """
    tid = trace_id or str(uuid4())
    token = _trace_id_ctx.set(tid)
    try:
        yield tid
    finally:
        _trace_id_ctx.reset(token)


@asynccontextmanager
async def bind_trace_id_async(trace_id: str | None = None):
    """`bind_trace_id` 的 async 版本，用于 `async with` 场景。"""
    tid = trace_id or str(uuid4())
    token = _trace_id_ctx.set(tid)
    try:
        yield tid
    finally:
        _trace_id_ctx.reset(token)


# ── RAG 全链路分步计时器（services/rag_service.py 依赖此契约）──
class StepTimer:
    """RAG 全链路分步计时器：对每一步掐表，既记录 Prometheus 指标又给出可返回的分段耗时。

    生活化类比：外卖从下单到送达，StepTimer 像一张"分段计时单"——
    接单、取餐、配送各自掐表，最后你能一眼看出哪一段最慢。

    契约（services/rag_service.py 已按此调用）：
        timer = StepTimer()
        rewritten = await timer.run("rewrite", rewrite_query(q))   # 传入协程
        chunks   = await timer.run("hybrid",  hybrid_search(...))
        timer.log()                # 打印各段耗时摘要
        return answer, timer.steps # steps: {"rewrite": 0.01, "hybrid": 0.20, ...}
    """

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
