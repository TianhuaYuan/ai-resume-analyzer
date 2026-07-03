import logging
import tempfile
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.auth import router as auth_router
from api.qa import router as qa_router
from api.resumes import router as resumes_router
from core.database import init_db

LOG_DIR = Path(tempfile.gettempdir()) / "ai-resume-analyzer"
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)-10s | %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.FileHandler(str(LOG_DIR / "app.log"), encoding="utf-8"),
        logging.StreamHandler(),
    ],
)

app = FastAPI(title="AI简历分析系统", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:5174"],
    allow_credentials=True,
    allow_methods=["*"],  # TODO: 上线前收紧
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(resumes_router)
app.include_router(qa_router)


@app.on_event("startup")
async def startup():
    await init_db()


@app.get("/", tags=["health"])
async def root():
    return {"status": "ok"}
