from fastapi import APIRouter, Depends, Request
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.database import get_db
from core.limiter import limiter
from schemas.auth import RegisterRequest, LoginRequest, RefreshRequest, TokenResponse, UserResponse
from services.auth_service import register_user, authenticate_user, create_tokens, refresh_token

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserResponse, status_code=201)
@limiter.limit(settings.RATE_LIMIT_REGISTER)
async def register(request: Request, data: RegisterRequest, db: AsyncSession = Depends(get_db)):
    """注册。Pydantic 已校验邮箱格式+密码长度+两次一致。"""
    user = await register_user(db, data)
    return user


@router.post("/login", response_model=TokenResponse)
@limiter.limit(settings.RATE_LIMIT_LOGIN)
async def login(request: Request, data: LoginRequest, db: AsyncSession = Depends(get_db)):
    """登录（JSON）。前端调这个，POST body 传 {email, password}。"""
    user = await authenticate_user(db, data.email, data.password)
    return create_tokens(user)


@router.post("/token", response_model=TokenResponse)
@limiter.limit(settings.RATE_LIMIT_LOGIN)
async def login_form(
    request: Request,
    form: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db),
):
    """登录（form）。Swagger UI 的 Authorize 按钮走的这个，username 字段填邮箱。"""
    user = await authenticate_user(db, form.username, form.password)
    return create_tokens(user)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(data: RefreshRequest, db: AsyncSession = Depends(get_db)):
    """刷新 token。用 refresh_token 换新的 access_token 对。"""
    return await refresh_token(db, data.refresh_token)
