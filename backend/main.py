from contextlib import asynccontextmanager
import shutil
import sys

from fastapi import FastAPI, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from slowapi.errors import RateLimitExceeded
from sqlalchemy import text

from core.limiter import limiter
from core.logging_config import setup_logging
from core.request_id import RequestIDMiddleware
from core.exceptions import AppException, register_exception_handlers
from core.config import settings
from core.database import engine, init_db
from core.metrics import (
    MetricsMiddleware,
    initialize_app_info,
    prometheus_metrics_endpoint,
)

from api.v1.router import v1_router

import logging

# 结构化日志（必须在其他模块 import 之前初始化）
setup_logging(settings.LOG_LEVEL)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：启动时验证数据库 + 清理孤儿 ChromaDB 目录 + 初始化 MCP Server + Metrics。"""
    await init_db()

    initialize_app_info(
        version="0.2.0",
        environment=settings.ENVIRONMENT,
        python_version=f"{sys.version_info.major}.{sys.version_info.minor}",
    )

    try:
        from services.rag_service import _cleanup_orphan_segments

        cleaned = _cleanup_orphan_segments()
        if cleaned:
            logger.info("Cleaned up %d orphan ChromaDB segments", cleaned)
    except Exception:
        logger.warning("Orphan cleanup skipped", exc_info=True)

    # 初始化 MCP Server（注册 Tool 和 Resource）
    try:
        from mcp_server.transport.http import init_mcp_server

        init_mcp_server()
        logger.info("MCP Server initialized")
    except Exception as e:
        logger.warning("MCP Server init skipped: %s", e)

    yield

    # 关闭 MCP Server
    try:
        from mcp_server.transport.http import shutdown_mcp_server

        await shutdown_mcp_server()
    except Exception:
        pass


app = FastAPI(title="AI简历分析系统", version="0.2.0", lifespan=lifespan)
app.state.limiter = limiter

app.add_middleware(RequestIDMiddleware)
app.add_middleware(MetricsMiddleware)
register_exception_handlers(app)


@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return Response(
        content='{"detail":"请求过于频繁，请稍后再试"}',
        status_code=429,
        media_type="application/json",
    )


cors_origins = [o.strip() for o in settings.CORS_ORIGINS.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response: Response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "0"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response


app.include_router(v1_router, prefix="/api/v1")

try:
    from mcp_server.transport.http import get_mcp_app

    app.mount("/mcp", get_mcp_app())
    logger.info("MCP Server mounted at /mcp")
except Exception as e:
    logger.warning("MCP Server mount skipped: %s", e)

LEGACY_PREFIXES = ["/api/auth", "/api/resumes", "/api/qa"]


@app.middleware("http")
async def legacy_redirect(request: Request, call_next):
    """旧版 /api/auth|resumes|qa 路径 301 到 /api/v1/..."""
    path = request.url.path
    # 快速过滤：非 /api/ 路径直接放行
    if not path.startswith("/api/"):
        return await call_next(request)
    for prefix in LEGACY_PREFIXES:
        if path.startswith(prefix):
            new_path = path.replace("/api/", "/api/v1/", 1)
            return RedirectResponse(url=new_path, status_code=308)
    return await call_next(request)


@app.get("/metrics", tags=["monitoring"], include_in_schema=False)
async def metrics():
    return await prometheus_metrics_endpoint(None)  # type: ignore[arg-type]


@app.get("/", tags=["health"])
async def health(verbose: bool = Query(False, description="返回详细检查信息")):
    checks: dict = {}
    all_ok = True

    # MySQL 连通性
    try:
        async with engine.begin() as conn:
            await conn.execute(text("SELECT 1"))
        checks["database"] = "connected"
    except Exception as e:
        checks["database"] = "disconnected"
        all_ok = False

    # ChromaDB 连通性
    try:
        from services.rag_service import get_chroma_client

        get_chroma_client().list_collections()
        checks["chromadb"] = "connected"
    except Exception as e:
        checks["chromadb"] = "disconnected"
        all_ok = False

    # LLM 服务可达性（verbose 模式 — 轻量 ping，不调用生成）
    if verbose:
        try:
            import httpx

            llm_base = settings.CHAT_BASE_URL
            # 使用短超时避免阻塞健康检查
            async with httpx.AsyncClient(timeout=3.0) as client:
                resp = await client.get(llm_base)
                checks["llm_service"] = "reachable" if resp.status_code < 500 else "degraded"
        except Exception:
            checks["llm_service"] = "unreachable"
            # LLM 不可达不标记整体 degraded（可能只是临时网络抖动）

    # 磁盘空间（仅 verbose 模式）
    if verbose:
        try:
            usage = shutil.disk_usage("/")
            free_gb = round(usage.free / (1024**3), 2)
            total_gb = round(usage.total / (1024**3), 2)
            percent_used = round((usage.used / usage.total) * 100, 1)
            checks["disk"] = {
                "free_gb": free_gb,
                "total_gb": total_gb,
                "percent_used": percent_used,
            }
            if percent_used > 95:
                all_ok = False
        except Exception:
            checks["disk"] = "unavailable"

    status_code = 200 if all_ok else 503
    checks["status"] = "ok" if all_ok else "degraded"

    return JSONResponse(content=checks, status_code=status_code)
