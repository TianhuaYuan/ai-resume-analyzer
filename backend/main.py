from contextlib import asynccontextmanager
import hmac
import json
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

    # P1-13：恢复卡住的简历（进程崩溃后 status=processing 的记录永远无法完成）
    try:
        from services.resume_service import recover_stuck_resumes

        recovered = await recover_stuck_resumes()
        if recovered:
            logger.warning("Recovered %d stuck resumes on startup", recovered)
    except Exception:
        logger.warning("Stuck resume recovery skipped", exc_info=True)

    # 初始化 MCP Server（注册 Tool 和 Resource）
    # Task 1.4: 记录 MCP 健康状态到 app.state，供 /health 探针读取
    app.state.mcp_healthy = False  # 默认不健康，初始化成功后置 True
    try:
        from mcp_server.transport.http import init_mcp_server

        init_mcp_server()
        app.state.mcp_healthy = True
        logger.info("MCP Server initialized")
    except Exception as e:
        app.state.mcp_healthy = False
        logger.warning("MCP Server init skipped: %s", e)

    yield

    # 关闭 Redis 连接
    try:
        from core.redis_client import close_redis

        await close_redis()
    except Exception:
        pass

    # 优雅关闭数据库连接池
    await engine.dispose()

    # 关闭 MCP Server
    try:
        from mcp_server.transport.http import shutdown_mcp_server

        await shutdown_mcp_server()
    except Exception:
        pass


def _docs_enabled() -> bool:
    """Task 1.4: 生产环境关闭 Swagger/OpenAPI 文档暴露。

    生产环境暴露 /docs /redoc /openapi.json 会泄露 API 结构，方便攻击者
    构造针对性请求。仅 production 关闭，staging 保留方便联调。
    """
    return settings.ENVIRONMENT != "production"


app = FastAPI(
    title="AI简历分析系统",
    version="0.2.0",
    lifespan=lifespan,
    docs_url="/docs" if _docs_enabled() else None,
    redoc_url="/redoc" if _docs_enabled() else None,
    openapi_url="/openapi.json" if _docs_enabled() else None,
)
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
    # P2-14：添加 Retry-After 头，让用户知道多久后可重试
    # slowapi 的 exc.limit.period 是限流窗口秒数（如 60s 内 10 次）
    retry_after = getattr(getattr(exc, "limit", None), "period", 60) or 60
    return Response(
        content=json.dumps(
            {"detail": f"请求过于频繁，请 {retry_after} 秒后再试"},
            ensure_ascii=False,
        ),
        status_code=429,
        media_type="application/json",
        headers={"Retry-After": str(retry_after)},
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

# P0-9：代理头处理（必须在 CORS 之后添加 → 执行顺序在 CORS 之前）
# 重写 request.client.host 为 X-Forwarded-For 中的真实 IP，trusted_hosts 限制为 Docker 内网
# 注意：Starlette 1.x 无 ProxyHeadersMiddleware，自实现轻量版
import ipaddress


class SimpleProxyHeadersMiddleware:
    """轻量代理头处理：可信来源的请求，把 request.client.host 改写为 X-Forwarded-For 首个 IP。"""

    def __init__(self, app, trusted_hosts=None):
        self.app = app
        self.trusted_hosts = trusted_hosts or ["*"]

    def _is_trusted(self, client_host: str) -> bool:
        if "*" in self.trusted_hosts:
            return True
        try:
            ip = ipaddress.ip_address(client_host)
        except ValueError:
            return False
        for cidr in self.trusted_hosts:
            try:
                if ip in ipaddress.ip_network(cidr, strict=False):
                    return True
            except ValueError:
                continue
        return False

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        client = scope.get("client")
        if client and self._is_trusted(client[0]):
            headers = dict(scope.get("headers", []))
            xff = headers.get(b"x-forwarded-for")
            if xff:
                real_ip = xff.decode().split(",")[0].strip()
                if real_ip:
                    scope["client"] = (real_ip, client[1])
            x_real_ip = headers.get(b"x-real-ip")
            if x_real_ip:
                real_ip = x_real_ip.decode().strip()
                if real_ip:
                    scope["client"] = (real_ip, client[1])
        return await self.app(scope, receive, send)


app.add_middleware(
    SimpleProxyHeadersMiddleware,
    trusted_hosts=["172.16.0.0/12", "10.0.0.0/8", "127.0.0.1"],
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response: Response = await call_next(request)
    # 3.1 SEC-006：HSTS（仅 HTTPS 生效，HTTP 下浏览器忽略）
    # P2-5: CSP 已迁移到 nginx（后端只服务 API，CSP 由 nginx 统一管理前端+API 响应）
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains; preload"
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
        if not hmac.compare_digest(auth, f"Bearer {expected}"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Metrics endpoint requires authentication",
            )
    return await prometheus_metrics_endpoint(None)  # type: ignore[arg-type]


@app.get("/", tags=["health"])
async def health(request: Request, verbose: bool = Query(False, description="返回详细检查信息")):
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

    # Task 1.4: MCP 健康探针（读取 lifespan 写入的 app.state.mcp_healthy）
    # MCP 不可用不标记整体 degraded：MCP 是辅助能力，挂了不影响核心 RAG/QA 流程
    mcp_healthy = getattr(request.app.state, "mcp_healthy", False)
    checks["mcp"] = "healthy" if mcp_healthy else "unhealthy"

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
