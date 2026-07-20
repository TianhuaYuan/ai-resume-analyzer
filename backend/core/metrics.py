"""Prometheus Metrics：HTTP/RAG/LLM/业务/系统四层指标。"""

from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from functools import wraps
from typing import Any, Callable

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    Info,
    generate_latest,
)
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger(__name__)

REGISTRY = CollectorRegistry(auto_describe=True)

DEFAULT_BUCKETS = (0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0)
RAG_BUCKETS = (0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0)
LLM_BUCKETS = (0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0, 120.0)

request_count = Counter(
    "app_http_requests_total",
    "HTTP 请求总数",
    ["method", "endpoint", "status_code"],
    registry=REGISTRY,
)

request_duration = Histogram(
    "app_http_request_duration_seconds",
    "HTTP 请求响应时间（秒）",
    ["method", "endpoint"],
    buckets=DEFAULT_BUCKETS,
    registry=REGISTRY,
)

request_in_progress = Gauge(
    "app_http_requests_in_progress",
    "当前正在处理的 HTTP 请求数",
    ["method", "endpoint"],
    registry=REGISTRY,
)

active_connections = Gauge(
    "app_http_active_connections",
    "当前活跃连接数",
    registry=REGISTRY,
)

rag_step_duration = Histogram(
    "app_rag_step_duration_seconds",
    "RAG 流水线各步骤耗时（秒）",
    ["step"],
    buckets=RAG_BUCKETS,
    registry=REGISTRY,
)

rag_step_errors = Counter(
    "app_rag_step_errors_total",
    "RAG 流水线各步骤错误计数",
    ["step", "error_type"],
    registry=REGISTRY,
)

rag_search_results_count = Histogram(
    "app_rag_search_results_count",
    "检索返回结果数量分布",
    ["stage"],
    buckets=(1, 2, 3, 5, 8, 10, 15, 20, 30, 50),
    registry=REGISTRY,
)

rag_retry_count = Counter(
    "app_rag_retries_total",
    "RAG 生成重试次数",
    registry=REGISTRY,
)

llm_call_count = Counter(
    "app_llm_calls_total",
    "LLM API 调用总数",
    ["model", "operation"],
    registry=REGISTRY,
)

llm_call_duration = Histogram(
    "app_llm_call_duration_seconds",
    "LLM API 调用耗时（秒）",
    ["model", "operation"],
    buckets=LLM_BUCKETS,
    registry=REGISTRY,
)

llm_token_usage = Counter(
    "app_llm_tokens_total",
    "LLM Token 消耗",
    ["model", "type"],
    registry=REGISTRY,
)

llm_call_errors = Counter(
    "app_llm_call_errors_total",
    "LLM API 调用错误计数",
    ["model", "operation", "error_type"],
    registry=REGISTRY,
)

resume_upload_count = Counter(
    "app_resume_uploads_total",
    "简历上传总数",
    ["status"],
    registry=REGISTRY,
)

resume_processing_duration = Histogram(
    "app_resume_processing_duration_seconds",
    "简历处理（解析+分块+向量化）耗时",
    buckets=DEFAULT_BUCKETS,
    registry=REGISTRY,
)

qa_session_count = Counter(
    "app_qa_sessions_total",
    "问答会话总数",
    ["mode"],
    registry=REGISTRY,
)

process_memory_rss = Gauge(
    "app_process_memory_rss_bytes",
    "进程 RSS 内存（字节）",
    registry=REGISTRY,
)

process_cpu_usage = Gauge(
    "app_process_cpu_usage_percent",
    "进程 CPU 使用率（%）",
    registry=REGISTRY,
)

process_threads = Gauge(
    "app_process_threads_total",
    "进程线程数",
    registry=REGISTRY,
)

app_info = Info(
    "app",
    "应用元信息",
    registry=REGISTRY,
)


async def prometheus_metrics_endpoint(request: Request) -> Response:
    _collect_system_metrics()
    return Response(
        content=generate_latest(REGISTRY),
        media_type=CONTENT_TYPE_LATEST,
    )


def _collect_system_metrics() -> None:
    try:
        import os
        import psutil

        process = psutil.Process(os.getpid())
        mem_info = process.memory_info()
        process_memory_rss.set(mem_info.rss)
        cpu_pct = process.cpu_percent(interval=0)
        process_cpu_usage.set(cpu_pct)
        process_threads.set(process.num_threads())
    except ImportError:
        pass
    except Exception as exc:
        logger.debug("system metrics collection failed: %s", exc)


_ENDPOINT_NORMALIZERS: list[tuple[str, str]] = [
    (r"/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", "/{id}"),
    (r"/\d+", "/{id}"),
    (r"/[0-9a-f]{24}", "/{id}"),
]

try:
    import re

    _compiled_normalizers = [
        (re.compile(pattern), replacement) for pattern, replacement in _ENDPOINT_NORMALIZERS
    ]

    def _normalize_endpoint(path: str) -> str:
        normalized = path
        for pattern, replacement in _compiled_normalizers:
            normalized = pattern.sub(replacement, normalized)
        return normalized

except ImportError:

    def _normalize_endpoint(path: str) -> str:  # type: ignore[misc]
        return path


class MetricsMiddleware(BaseHTTPMiddleware):
    _HEALTH_PATHS = frozenset({"/", "/health", "/health/verbose"})

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        method = request.method
        path = request.url.path
        endpoint = _normalize_endpoint(path)

        is_health_check = path in self._HEALTH_PATHS
        is_metrics_endpoint = path == "/metrics"

        if not is_metrics_endpoint:
            active_connections.inc()

        if not is_health_check and not is_metrics_endpoint:
            request_in_progress.labels(method=method, endpoint=endpoint).inc()

        start_time = time.perf_counter()

        try:
            response = await call_next(request)
        except Exception:
            status_code = "500"
            raise
        else:
            status_code = str(response.status_code)
            return response
        finally:
            elapsed = time.perf_counter() - start_time

            if not is_metrics_endpoint:
                active_connections.dec()

            if not is_health_check and not is_metrics_endpoint:
                request_in_progress.labels(method=method, endpoint=endpoint).dec()
                request_count.labels(
                    method=method, endpoint=endpoint, status_code=status_code
                ).inc()
                request_duration.labels(method=method, endpoint=endpoint).observe(elapsed)


@contextmanager
def timer_context(step: str):
    start = time.perf_counter()
    try:
        yield
    except Exception as exc:
        rag_step_errors.labels(step=step, error_type=type(exc).__name__).inc()
        raise
    finally:
        elapsed = time.perf_counter() - start
        rag_step_duration.labels(step=step).observe(elapsed)


# OBS-004：timer_context 的 async 版本，支持 `async with`。
# 注意：不能用 `async def` + `yield` 的异步生成器直接配 `async with`
# （它缺少 __aenter__/__aexit__ 协议），故用类实现。
# 用法：
#   async with async_timer_context("retrieve"):
#       docs = await vector_search(...)
# 同步代码仍用 timer_context（保持向后兼容，不删不改）。
class async_timer_context:
    """`async with` 版的 RAG 步骤计时器（OBS-004）。"""

    def __init__(self, step: str) -> None:
        self._step = step
        self._start: float | None = None

    async def __aenter__(self) -> "async_timer_context":
        self._start = time.perf_counter()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        elapsed = time.perf_counter() - (self._start or time.perf_counter())
        if exc_type is not None:
            rag_step_errors.labels(step=self._step, error_type=exc_type.__name__).inc()
        rag_step_duration.labels(step=self._step).observe(elapsed)
        return False  # 不吞异常，原样向上抛


def track_llm_call(model: str, operation: str) -> Callable:
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            llm_call_count.labels(model=model, operation=operation).inc()
            start = time.perf_counter()
            try:
                result = await func(*args, **kwargs)
                return result
            except Exception as exc:
                llm_call_errors.labels(
                    model=model, operation=operation, error_type=type(exc).__name__
                ).inc()
                raise
            finally:
                elapsed = time.perf_counter() - start
                llm_call_duration.labels(model=model, operation=operation).observe(elapsed)

        return wrapper

    return decorator


def record_token_usage(model: str, prompt_tokens: int, completion_tokens: int) -> None:
    if prompt_tokens > 0:
        llm_token_usage.labels(model=model, type="prompt").inc(prompt_tokens)
    if completion_tokens > 0:
        llm_token_usage.labels(model=model, type="completion").inc(completion_tokens)


def initialize_app_info(version: str, environment: str, python_version: str) -> None:
    app_info.info(
        {
            "version": version,
            "environment": environment,
            "python_version": python_version,
        }
    )
