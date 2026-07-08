"""v1 路由汇总：auth + resumes + qa。"""
from fastapi import APIRouter

from api.auth import router as auth_router
from api.qa import router as qa_router
from api.resumes import router as resumes_router

v1_router = APIRouter()

v1_router.include_router(auth_router)
v1_router.include_router(resumes_router)
v1_router.include_router(qa_router)
