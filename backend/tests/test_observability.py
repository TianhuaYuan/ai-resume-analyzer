"""阶段10 可观测性验收测试（OBS-001~004 相关能力）。

TDD 纪律：先写测试（RED），再实现 core/metrics.py 增强 + 新建 core/trace.py（GREEN）。

独立运行（不依赖 MySQL / ChromaDB / MCP，自建最小 ASGI app）：
    cd backend && python -m pytest tests/test_observability.py -q

覆盖点：
- /metrics 暴露请求延迟直方图（OBS：请求延迟直方图）
- 请求计数按 route / status_code 维度（OBS：按 route/status 的计数器）
- trace_id 在请求上下文内可获取、且与 X-Request-ID 对齐（阶段10 核心：trace 透传）
- async_timer_context 记录 RAG 步骤耗时（OBS-004：timer async 化）
- track_llm_call 计数 LLM 调用（OBS-001）
- 非 HTTP 上下文 bind_trace_id 手动绑定运单号
"""

import time

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from core.metrics import (
    MetricsMiddleware,
    async_timer_context,
    prometheus_metrics_endpoint,
    track_llm_call,
)
from core.request_id import RequestIDMiddleware
from core.trace import StepTimer, TraceMiddleware, bind_trace_id, get_trace_id


def _build_app() -> FastAPI:
    """自建最小 app：仅装可观测性中间件，不触碰数据库 / MCP。"""
    app = FastAPI()

    @app.get("/echo")
    async def echo():
        return {"ok": True}

    @app.get("/metrics")
    async def metrics():
        # 测试用最小 /metrics 端点（与 main.py 中的接线等价，本阶段不改动 main.py）
        return await prometheus_metrics_endpoint(None)

    @app.get("/trace")
    async def trace():
        # 关键断言点：请求处理函数内能取到与 X-Request-ID 对齐的 trace_id
        return {"trace_id": get_trace_id()}

    @app.get("/rag-step")
    async def rag_step():
        async with async_timer_context("test_step"):  # OBS-004
            time.sleep(0.001)
        return {"ok": True}

    @track_llm_call(model="test-model", operation="test-op")  # OBS-001
    async def _fake_llm():
        return "done"

    @app.get("/llm")
    async def llm():
        await _fake_llm()
        return {"ok": True}

    # 装配顺序：RequestIDMiddleware（最外）→ MetricsMiddleware → TraceMiddleware（最内）。
    # 越靠后 add_middleware 越靠外层；TraceMiddleware 直接读请求头，不依赖顺序。
    app.add_middleware(TraceMiddleware)
    app.add_middleware(MetricsMiddleware)
    app.add_middleware(RequestIDMiddleware)
    return app


@pytest_asyncio.fixture
async def client():
    transport = ASGITransport(app=_build_app())
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ── OBS：请求延迟直方图 + 按 route/status 计数 ──
async def test_metrics_endpoint_exposes_latency_histogram_and_count(client):
    await client.get("/echo")
    body = (await client.get("/metrics")).text
    # 请求延迟直方图（按 method/endpoint）
    assert "app_http_request_duration_seconds" in body
    # 请求计数（按 method/endpoint/status_code）
    assert "app_http_requests_total" in body
    # 维度正确：route + status
    assert 'endpoint="/echo"' in body
    assert 'status_code="200"' in body


async def test_request_count_excludes_metrics_endpoint(client):
    # /metrics 自身不应被计入请求数（避免自循环 + 污染基数）
    await client.get("/metrics")
    body = (await client.get("/metrics")).text
    # 没有因访问 /metrics 而产生 endpoint="/metrics" 的计数
    assert 'endpoint="/metrics"' not in body


# ── 阶段10 核心：trace_id 在请求内透传，并与 X-Request-ID 对齐 ──
async def test_trace_id_propagated_and_aligned_with_request_id(client):
    rid = "req-abc-123"
    resp = await client.get("/trace", headers={"X-Request-ID": rid})
    assert resp.status_code == 200
    assert resp.json()["trace_id"] == rid
    # 响应头回写 X-Trace-ID，前端排障可原样带回
    assert resp.headers.get("X-Trace-ID") == rid


async def test_trace_id_generated_when_header_missing(client):
    resp = await client.get("/trace")
    tid = resp.json()["trace_id"]
    assert tid and tid != "-"
    assert resp.headers.get("X-Trace-ID") == tid


async def test_trace_id_request_isolated(client):
    # 两次请求运单号应不同（contextvars 隔离，不串号）
    t1 = (await client.get("/trace")).json()["trace_id"]
    t2 = (await client.get("/trace")).json()["trace_id"]
    assert t1 != t2


# ── OBS-004：async_timer_context 记录 RAG 步骤耗时 ──
async def test_async_timer_context_records_rag_step(client):
    await client.get("/rag-step")
    body = (await client.get("/metrics")).text
    assert "app_rag_step_duration_seconds" in body


# ── OBS-001：track_llm_call 计数 LLM 调用 ──
async def test_track_llm_call_records_counter(client):
    await client.get("/llm")
    body = (await client.get("/metrics")).text
    assert "app_llm_calls_total" in body


# ── 非 HTTP 上下文：手动绑定运单号 ──
def test_bind_trace_id_outside_request():
    assert get_trace_id() == "-"
    with bind_trace_id("job-7") as tid:
        assert tid == "job-7"
        assert get_trace_id() == "job-7"
    # 退出上下文后恢复默认，不污染后续
    assert get_trace_id() == "-"


# ── 跨阶段契约：StepTimer（services/rag_service.py 依赖）──
def test_step_timer_records_steps_and_metrics():
    async def _noop():
        return 42

    async def _boom():
        raise ValueError("x")

    async def _run():
        t = StepTimer()
        val = await t.run("rewrite", _noop())
        assert val == 42
        assert "rewrite" in t.steps and t.steps["rewrite"] >= 0
        try:
            await t.run("bad", _boom())
        except ValueError:
            pass
        t.log()
        return t

    import asyncio

    t = asyncio.run(_run())
    assert "bad" in t.steps  # 异常步骤也记录耗时
    # 指标侧：RAG 步骤耗时直方图已暴露
    from core.metrics import rag_step_duration

    assert rag_step_duration is not None

