from fastapi import APIRouter, Depends, Request, Response
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.database import get_db
from core.limiter import limiter
from core.security import (
    clear_auth_cookies,
    decode_token,
    extract_token_from_request,
    revoke_token,
    set_auth_cookies,
)
from schemas.auth import RegisterRequest, LoginRequest, RefreshRequest, TokenResponse, UserResponse
from services.auth_service import register_user, authenticate_user, create_tokens, refresh_token

router = APIRouter(prefix="/auth", tags=["auth"])


def _cookie_max_age() -> tuple[int, int]:
    """返回 (access_max_age 秒, refresh_max_age 秒)。"""
    return (
        settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400,
    )


@router.post("/register", response_model=UserResponse, status_code=201)
@limiter.limit(settings.RATE_LIMIT_REGISTER)
async def register(request: Request, data: RegisterRequest, db: AsyncSession = Depends(get_db)):
    """注册。Pydantic 已校验邮箱格式+密码长度+两次一致。"""
    user = await register_user(db, data)
    return user


@router.post("/login", response_model=TokenResponse)
@limiter.limit(settings.RATE_LIMIT_LOGIN)
async def login(
    request: Request,
    response: Response,
    data: LoginRequest,
    db: AsyncSession = Depends(get_db),
):
    """登录（JSON）。前端调这个，POST body 传 {email, password}。

    SEC-004：同时下发 HttpOnly Cookie（更安全的可选通道），并保留 JSON Bearer
    以便既有前端零改动。
    """
    user = await authenticate_user(db, data.email, data.password)
    tokens = create_tokens(user)
    a_max, r_max = _cookie_max_age()
    set_auth_cookies(
        response,
        tokens.access_token,
        tokens.refresh_token,
        access_max_age=a_max,
        refresh_max_age=r_max,
    )
    return tokens


@router.post("/token", response_model=TokenResponse)
@limiter.limit(settings.RATE_LIMIT_LOGIN)
async def login_form(
    request: Request,
    response: Response,
    form: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db),
):
    """登录（form）。Swagger UI 的 Authorize 按钮走的这个，username 字段填邮箱。"""
    user = await authenticate_user(db, form.username, form.password)
    tokens = create_tokens(user)
    a_max, r_max = _cookie_max_age()
    set_auth_cookies(
        response,
        tokens.access_token,
        tokens.refresh_token,
        access_max_age=a_max,
        refresh_max_age=r_max,
    )
    return tokens


@router.post("/refresh", response_model=TokenResponse)
@limiter.limit(settings.RATE_LIMIT_REFRESH)  # SEC-003：refresh 限流，防刷新凭证爆破
async def refresh(
    request: Request,
    response: Response,
    data: RefreshRequest,
    db: AsyncSession = Depends(get_db),
):
    """刷新 token。用 refresh_token 换新的 access_token 对。

    SEC-004：刷新后同步轮换 cookie。
    """
    tokens = await refresh_token(db, data.refresh_token)
    a_max, r_max = _cookie_max_age()
    set_auth_cookies(
        response,
        tokens.access_token,
        tokens.refresh_token,
        access_max_age=a_max,
        refresh_max_age=r_max,
    )
    return tokens


@router.post("/logout", status_code=200)
async def logout(request: Request, response: Response):
    """登出：撤销当前 access token（SEC-005）+ 清除 HttpOnly Cookie（SEC-004）。

    双模取 token：Bearer 或 Cookie 均可。无 token 也幂等返回（仅清 cookie）。
    """
    token = extract_token_from_request(request)
    if token:
        payload = decode_token(token)
        if payload is not None:
            # 只撤销 access；refresh 在 cookie 里随后被清除，等同失效
            revoke_token(payload.get("jti"))
    clear_auth_cookies(response)
    return {"detail": "已登出"}
