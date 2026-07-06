import logging
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from slowapi.errors import RateLimitExceeded

from core.limiter import limiter
from sqlalchemy import text

from api.auth import router as auth_router
from api.qa import router as qa_router
from api.resumes import router as resumes_router
from core.config import settings
from core.database import engine, init_db

logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s | %(levelname)-8s | %(name)-15s | %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：启动时验证数据库 + 清理孤儿 ChromaDB 目录。"""
    await init_db()
    try:
        from services.rag_service import _cleanup_orphan_segments

        cleaned = _cleanup_orphan_segments()
        if cleaned:
            logger.info("Cleaned up %d orphan ChromaDB segments", cleaned)
    except Exception as e:
        logger.warning("Orphan cleanup skipped: %s", e)
    yield


app = FastAPI(title="AI简历分析系统", version="0.1.0", lifespan=lifespan)
app.state.limiter = limiter


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


app.include_router(auth_router)
app.include_router(resumes_router)
app.include_router(qa_router)


@app.get("/", tags=["health"])
async def health():
    checks: dict = {"status": "ok"}

    try:
        async with engine.begin() as conn:
            await conn.execute(text("SELECT 1"))
        checks["database"] = "connected"
    except Exception:
        checks["database"] = "disconnected"

    try:
        from services.rag_service import get_chroma_client

        get_chroma_client().list_collections()
        checks["chromadb"] = "connected"
    except Exception:
        checks["chromadb"] = "disconnected"

    if any(v != "connected" for k, v in checks.items() if k != "status"):
        checks["status"] = "degraded"

    return checks
