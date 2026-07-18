from contextlib import asynccontextmanager
import shutil
import sys

from fastapi import FastAPI, HTTPException, Query, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from slowapi.errors import RateLimitExceeded
from sqlalchemy import text

from core.limiter import limiter
from core.logging_config import setup_logging
from core.request_id import RequestIDMiddleware
from core.exceptions import register_exception_handlers
from core.config import settings, validate_required_settings
from core.database import engine, init_db
from core.metrics import (
    MetricsMiddleware,
    initialize_app_info,
    prometheus_metrics_endpoint,
)
from core.trace import install_trace_middleware, install_trace_logging

from api.v1.router import v1_router

import logging

# 结构化日志（必须在其他模块 import 之前初始化）
setup_logging(settings.LOG_LEVEL)
# 阶段10 OBS：给所有日志注入 trace_id（与 X-Request-ID 对齐），便于按运单号检索链路
install_trace_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：启动时验证数据库 + 清理孤儿 ChromaDB 目录 + 初始化 MCP Server + Metrics。"""
    await init_db()
    # 3.6 N6：启动期 fail-fast 配置校验（生产/预发缺关键变量直接启动失败）
    validate_required_settings()

    initialize_app_info(
        version="0.2.0",
        environment=settings.ENVIRONMENT,
        python_version=f"{sys.version_info.major}.{sys.version_info.minor}",
    )

    try:
        from services.rag.clients import _cleanup_orphan_segments

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
# 阶段10 OBS：Trace 中间件（请求级 trace_id 透传 + 回写 X-Trace-ID 响应头）
install_trace_middleware(app)
register_exception_handlers(app)


# ── 阶段9 SEC-013：请求体大小限制（防超大请求体打满内存 DoS）──
# 类比：快递柜对每个包裹限重，超重直接拒收，不让你把整个仓库塞进来。
# 仅看 Content-Length 头（不读 body），超限即 413，开销极小。
@app.middleware("http")
async def limit_request_body(request: Request, call_next):
    raw = request.headers.get("content-length")
    if raw:
        try:
            length = int(raw)
        except ValueError:
            length = 0
        max_bytes = settings.MAX_REQUEST_BODY_MB * 1024 * 1024
        if length > max_bytes:
            return Response(
                content='{"detail":"请求体过大"}',
                status_code=413,
                media_type="application/json",
            )
    return await call_next(request)


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
    # 3.2 SEC-016：收紧允许的方法（仅实际使用的 GET/POST/DELETE）
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    # 3.2 SEC-016：收紧允许的头（前端实际发送的自定义头白名单，禁止 *）
    allow_headers=["Authorization", "Content-Type", "X-Request-ID", "Idempotency-Key"],
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response: Response = await call_next(request)
    # 3.1 SEC-006：HSTS（仅 HTTPS 生效，HTTP 下浏览器忽略）+ 严格 CSP
    response.headers["Strict-Transport-Security"] = (
        "max-age=31536000; includeSubDomains; preload"
    )
    response.headers["Content-Security-Policy"] = (
        "default-src 'none'; frame-ancestors 'none'; base-uri 'none'"
    )
    # 3.3 SEC-018：禁用浏览器敏感权限特性
    response.headers["Permissions-Policy"] = (
        "camera=(), geolocation=(), microphone=(), payment=(), usb=(), interest-cohort=()"
    )
    # 既有基础防护头
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "0"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

    # ── 阶段9 SEC-015/017：扩展安全响应头（不覆盖阶段3 已有权头）──
    # SEC-017：API 响应一律禁止缓存（防止令牌/隐私数据被代理或浏览器落盘）
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, private"
    # SEC-015：删除 Server 头，避免泄露后端技术栈（uvicorn 在 HTTP 层可能补回，
    #           这里尽力在应用层剥离；生产由反代/nginx 兜底）
    if "Server" in response.headers:
        del response.headers["Server"]
    # SEC-015：跨源隔离相关头，缩小被嵌入/被跨源读取的攻击面
    response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
    response.headers["Cross-Origin-Resource-Policy"] = "same-origin"
    # SEC-017：老 IE 下载嗅探防护 + 禁止跨域 Flash/PDF 策略文件
    response.headers["X-Download-Options"] = "noopen"
    response.headers["X-Permitted-Cross-Domain-Policies"] = "none"
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
async def metrics(request: Request):
    # 3.4 SEC-012：/metrics 访问控制。配置了 METRICS_TOKEN 时要求 Bearer 携带，
    # 否则 403；未配置（本地开发）则放行，避免阻断本地 Prometheus 抓取。
    expected = settings.METRICS_TOKEN
    if expected:
        auth = request.headers.get("authorization", "")
        if auth != f"Bearer {expected}":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Metrics endpoint requires authentication",
            )
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
    except Exception:
        checks["database"] = "disconnected"
        all_ok = False

    # ChromaDB 连通性
    try:
        from services.rag.clients import get_chroma_client

        get_chroma_client().list_collections()
        checks["chromadb"] = "connected"
    except Exception:
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
