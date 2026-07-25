from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_current_user
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
from models.user import User
from schemas.auth import (
    AdminResetPasswordRequest,
    AdminResetPasswordResponse,
    ForgotPasswordRequest,
    LoginRequest,
    MessageResponse,
    RefreshRequest,
    RegisterRequest,
    ResetPasswordRequest,
    TokenResponse,
    UserResponse,
)
from services.auth_service import (
    admin_reset_password,
    register_user,
    authenticate_user,
    complete_password_reset,
    create_tokens,
    initiate_password_reset,
    refresh_token,
)

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
@limiter.limit(settings.RATE_LIMIT_REFRESH)
async def refresh(
    request: Request,
    response: Response,
    data: RefreshRequest,
    db: AsyncSession = Depends(get_db),
):
    """刷新 token。用 refresh_token 换新的 access_token 对。

    P0-4：提取旧 access token 的 jti，传入 refresh_token 函数撤销。
    """
    # 提取旧 access token 的 jti
    access_token = extract_token_from_request(request)
    access_token_jti = None
    if access_token:
        access_payload = decode_token(access_token)
        if access_payload is not None:
            access_token_jti = access_payload.get("jti")

    tokens = await refresh_token(db, data.refresh_token, access_token_jti)
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
    """登出：撤销当前 access token + refresh token + 清除 HttpOnly Cookie。

    双模取 token：Bearer 或 Cookie 均可。无 token 也幂等返回（仅清 cookie）。
    """
    token = extract_token_from_request(request)
    if token:
        payload = decode_token(token)
        if payload is not None:
            await revoke_token(payload.get("jti"))

    # 同时撤销 refresh token（P0-3 修复）
    refresh_token_str = request.cookies.get(settings.REFRESH_COOKIE_NAME)
    if refresh_token_str:
        refresh_payload = decode_token(refresh_token_str)
        if refresh_payload is not None:
            await revoke_token(refresh_payload.get("jti"))

    clear_auth_cookies(response)
    return {"detail": "已登出"}


def _is_admin(user: User) -> bool:
    """检查用户是否在管理员邮箱列表中。"""
    admin_emails_setting = settings.ADMIN_EMAILS
    if isinstance(admin_emails_setting, str):
        admin_emails = [e.strip() for e in admin_emails_setting.split(",") if e.strip()]
    else:
        admin_emails = list(admin_emails_setting)
    return user.email in admin_emails


@router.post("/admin/reset-password", response_model=AdminResetPasswordResponse)
async def admin_reset_password_endpoint(
    data: AdminResetPasswordRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """管理员重置任意用户密码，返回新的临时密码。

    仅 settings.ADMIN_EMAILS 中的邮箱可调用，非管理员返回 403。
    """
    if not _is_admin(current_user):
        raise HTTPException(
            status_code=403,
            detail="需要管理员权限",
        )

    new_password = await admin_reset_password(db, data.email)
    return AdminResetPasswordResponse(email=data.email, new_password=new_password)


@router.post("/forgot-password", response_model=MessageResponse)
@limiter.limit(settings.RATE_LIMIT_PASSWORD_RESET)
async def forgot_password(
    request: Request,
    data: ForgotPasswordRequest,
    db: AsyncSession = Depends(get_db),
):
    """P1-23 方案 B：发起密码重置流程。

    无论邮箱是否存在都返回 200（防止用户枚举攻击）。
    - 用户存在：生成 reset token，开发环境写入日志（生产环境发邮件）
    - 用户不存在：静默忽略

    限流：3 次/分钟（爆破/滥用防御）。
    """
    await initiate_password_reset(db, data.email)
    return MessageResponse(detail="若邮箱存在，重置链接已发送")


@router.post("/reset-password", response_model=MessageResponse)
async def reset_password(
    data: ResetPasswordRequest,
    db: AsyncSession = Depends(get_db),
):
    """P1-23 方案 B：完成密码重置。

    验证 reset token 并更新密码：
    - token 无效/过期/类型错误→400
    - token 已使用（一次性）→400
    - 密码强度不足→422（Pydantic 校验）
    """
    await complete_password_reset(db, data.token, data.new_password)
    return MessageResponse(detail="密码已重置，请使用新密码登录")
