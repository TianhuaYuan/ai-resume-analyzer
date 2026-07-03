import logging
import sys

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
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

app = FastAPI(title="AI简历分析系统", version="0.1.0")

cors_origins = [o.strip() for o in settings.CORS_ORIGINS.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(resumes_router)
app.include_router(qa_router)


@app.on_event("startup")
async def startup():
    await init_db()


@app.get("/", tags=["health"])
async def health():
    checks: dict = {"status": "ok"}

    try:
        async with engine.begin() as conn:
            await conn.execute(text("SELECT 1"))
        checks["database"] = "connected"
    except Exception as e:
        checks["database"] = f"error: {e}"

    try:
        from services.rag_service import get_chroma_client

        get_chroma_client().list_collections()
        checks["chromadb"] = "connected"
    except Exception as e:
        checks["chromadb"] = f"error: {e}"

    if any(v != "connected" for k, v in checks.items() if k != "status"):
        checks["status"] = "degraded"

    return checks
