from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from core.database import init_db
from api.auth import router as auth_router

app = FastAPI(title="AI简历分析系统", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:5174"],
    allow_credentials=True,
    allow_methods=["*"],  # TODO: 上线前收紧
    allow_headers=["*"],
)

app.include_router(auth_router)


@app.on_event("startup")
async def startup():
    await init_db()


@app.get("/", tags=["health"])
async def root():
    return {"status": "ok"}
