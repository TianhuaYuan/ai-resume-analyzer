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
    verify_origin,
)
from models.user import User
from schemas.auth import (
    AdminResetPasswordRequest,
    AdminResetPasswordResponse,
    ChangeEmailRequest,
    ChangePasswordRequest,
    ChangeUsernameRequest,
    ForgotPasswordRequest,
    ForgotPasswordVerifyRequest,
    LoginRequest,
    MessageResponse,
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)
from services.audit_log_service import write_audit_log
from services.auth_service import (
    admin_reset_password,
    change_email as change_email_service,
    change_password as change_password_service,
    change_username as change_username_service,
    register_user,
    authenticate_user,
    create_tokens,
    refresh_token,
    reset_password_by_verification,
)
from services.analytics_service import record_event
from services.user_cleanup_service import delete_user_account
from services.verification_service import generate_code, store_code, verify_code

router = APIRouter(prefix="/auth", tags=["auth"])


def _cookie_max_age() -> tuple[int, int]:
    """返回 (access_max_age 秒, refresh_max_age 秒)。"""
    return (
        settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400,
    )


@router.post("/register", response_model=UserResponse, status_code=201)
@limiter.limit(settings.RATE_LIMIT_REGISTER)
async def register(
    request: Request,
    data: RegisterRequest,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_origin),
):
    """注册。需要先调用 /send-code 获取验证码。"""
    if not await verify_code(data.email, data.verification_code):
        raise HTTPException(status_code=400, detail="验证码无效或已过期")
    user = await register_user(db, data)
    # T37: 漏斗埋点（best-effort，失败不影响注册主流程）
    await record_event(db, user.id, "user.register", source=data.source)
    return user


@router.post("/send-code", response_model=MessageResponse)
@limiter.limit("3/minute")
async def send_code(
    request: Request,
    data: ForgotPasswordRequest,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_origin),
):
    """发送邮箱验证码（注册/忘记密码共用）。"""
    code = generate_code()
    await store_code(data.email, code)
    try:
        from services.email_sender import get_email_sender
        sender = get_email_sender()
        sender.send_verification_email(to=data.email, code=code)
    except Exception:
        logger.exception("验证码邮件发送失败: email=%s", data.email)
    return MessageResponse(detail="验证码已发送")


@router.post("/login", response_model=TokenResponse)
@limiter.limit(settings.RATE_LIMIT_LOGIN)
async def login(
    request: Request,
    response: Response,
    data: LoginRequest,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_origin),
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
    _: bool = Depends(verify_origin),
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
    _: bool = Depends(verify_origin),
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
    data: ForgotPasswordVerifyRequest,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_origin),
):
    """新流程：验证码通过后直接修改密码（无需邮件链接）。

    流程：
    1. 验证邮箱验证码
    2. 邮箱存在 → 直接更新密码（用户不存在静默返回 200 防枚举）
    3. 返回 200，前端提示用户用新密码登录
    """
    if not await verify_code(data.email, data.verification_code):
        raise HTTPException(status_code=400, detail="验证码无效或已过期")
    await reset_password_by_verification(db, data.email, data.new_password)
    return MessageResponse(detail="密码已重置，请使用新密码登录")


# ── 用户资料管理（需登录） ─────────────────────────────


@router.put("/password", response_model=MessageResponse)
async def change_password(
    request: Request,
    data: ChangePasswordRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _: bool = Depends(verify_origin),
):
    """修改密码。支持旧密码验证和邮箱验证码两种方式。"""
    await change_password_service(
        db=db,
        user=current_user,
        mode=data.mode,
        new_password=data.new_password,
        old_password=data.old_password,
        verification_code=data.verification_code,
    )

    # S1-T8: 记录审计日志
    await write_audit_log(
        db,
        user_id=current_user.id,
        action="change_password",
        target_type="user",
        target_id=str(current_user.id),
        detail={"mode": data.mode, "ip": request.client.host if request.client else None},
    )

    return MessageResponse(detail="密码修改成功")


@router.put("/email", response_model=MessageResponse)
async def change_email(
    request: Request,
    data: ChangeEmailRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _: bool = Depends(verify_origin),
):
    """修改邮箱。需要新邮箱的验证码。"""
    await change_email_service(
        db=db,
        user=current_user,
        new_email=data.new_email,
        verification_code=data.verification_code,
    )
    return MessageResponse(detail="邮箱修改成功")


@router.put("/username", response_model=MessageResponse)
async def change_username(
    request: Request,
    data: ChangeUsernameRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _: bool = Depends(verify_origin),
):
    """修改用户名。"""
    await change_username_service(
        db=db,
        user=current_user,
        new_username=data.new_username,
    )
    return MessageResponse(detail="用户名修改成功")


@router.get("/me", response_model=UserResponse)
async def get_me(current_user: User = Depends(get_current_user)):
    """获取当前登录用户信息（#9: 含 is_admin 用于前端控制管理入口可见性）。"""
    resp = UserResponse.model_validate(current_user)
    resp.is_admin = _is_admin(current_user)
    return resp


@router.get("/export-data")
async def export_user_data_endpoint(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """C3: 导出当前用户全量私有数据（JSON）。

    信任合规——用户有权带走自己的数据。返回账户/简历(含模块)/问答历史/
    求职跟踪/知识资产/意见反馈等按 user_id 归属的全部数据。

    错误码：
    - 401 未登录
    """
    from services.data_export_service import export_user_data

    return await export_user_data(db, current_user.id)


@router.delete("/account", status_code=204)
async def delete_account(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """删除当前用户账户，级联清理所有数据。"""
    user_id = current_user.id

    # S1-T8: 先写审计日志（用户删除后外键会失效）
    await write_audit_log(
        db,
        user_id=user_id,
        action="delete_account",
        target_type="user",
        target_id=str(user_id),
        detail={"ip": request.client.host if request.client else None},
    )

    await delete_user_account(db, current_user)
    return Response(status_code=204)
