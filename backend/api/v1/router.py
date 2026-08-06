"""v1 路由汇总：auth + resumes + qa + feedback + websocket + admin + analytics + assets。"""

from fastapi import APIRouter

from api.admin import router as admin_router
from api.analytics import router as analytics_router
from api.assets import router as assets_router
from api.auth import router as auth_router
from api.feedback import router as feedback_router
from api.interview import router as interview_router
from api.job_applications import router as job_applications_router
from api.qa import router as qa_router
from api.resumes import router as resumes_router
from api.websocket import router as websocket_router

v1_router = APIRouter()

v1_router.include_router(auth_router)
v1_router.include_router(resumes_router)
v1_router.include_router(qa_router)
v1_router.include_router(feedback_router)
v1_router.include_router(interview_router)
v1_router.include_router(job_applications_router)
v1_router.include_router(websocket_router)
v1_router.include_router(admin_router)
v1_router.include_router(analytics_router)
v1_router.include_router(assets_router)
