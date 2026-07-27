import logging
import secrets
import string

from fastapi import HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.security import (
    hash_password,
    verify_password,
    create_access_token,
    create_refresh_token,
    create_reset_token,
    decode_token,
    is_token_revoked,
    revoke_token,
)
from models.user import User
from schemas.auth import RegisterRequest, TokenResponse
from services.email_sender import get_email_sender

logger = logging.getLogger(__name__)


async def register_user(db: AsyncSession, data: RegisterRequest) -> User:
    """注册。用户名或邮箱重复→409。"""
    result = await db.execute(
        select(User).where(or_(User.username == data.username, User.email == data.email))
    )
    if result.scalar_one_or_none() is not None:
        logger.warning("注册冲突: username=%s, email=%s", data.username, data.email)
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="用户名或邮箱已被注册")

    user = User(
        username=data.username,
        email=data.email,
        password_hash=hash_password(data.password),
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def authenticate_user(db: AsyncSession, email: str, password: str) -> User:
    """登录验证。邮箱或密码错→401。"""
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if user is None or not verify_password(password, user.password_hash):
        logger.warning("登录失败: email=%s, user_exists=%s", email, user is not None)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="邮箱或密码错误")
    return user


def create_tokens(user: User) -> TokenResponse:
    """为一个用户生成 access + refresh token 对。"""
    data = {"sub": str(user.id)}
    return TokenResponse(
        access_token=create_access_token(data),
        refresh_token=create_refresh_token(data),
    )


async def refresh_token(db: AsyncSession, token_str: str, access_token_jti: str | None = None) -> TokenResponse:
    """用 refresh_token 换新 token 对。过期或 type 非 refresh→401。

    SEC-005：已被撤销的 refresh token（如其他端登出/改密后）直接拒。
    P0-4：同时撤销旧 access token，防止旧 token 在剩余有效期内被使用。
    """
    payload = decode_token(token_str)
    if payload is None or payload.get("type") != "refresh":
        logger.warning(
            "refresh token 无效: type=%s", payload.get("type") if payload else "decode_failed"
        )
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="无效或过期的刷新凭证")

    # SEC-005：撤销名单校验（登出/改密后旧 refresh 失效）
    if await is_token_revoked(payload.get("jti")):
        logger.warning("refresh token 已撤销: jti=%s", payload.get("jti"))
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="刷新凭证已失效，请重新登录"
        )

    user_id_str = payload.get("sub")
    if user_id_str is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="凭证内容无效")
    try:
        user_id = int(user_id_str)
    except (ValueError, TypeError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="凭证内容无效")

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户不存在")

    # 撤销旧 refresh token，防止 token 轮换后旧 token 仍可使用
    await revoke_token(payload.get("jti"))

    # P0-4：撤销旧 access token
    if access_token_jti:
        await revoke_token(access_token_jti)

    return create_tokens(user)


def _generate_temp_password(length: int = 12) -> str:
    """生成符合强度要求的临时密码。"""
    alphabet = string.ascii_letters + string.digits
    while True:
        pwd = "".join(secrets.choice(alphabet) for _ in range(length))
        if any(c.isalpha() for c in pwd) and any(c.isdigit() for c in pwd):
            return pwd


async def admin_reset_password(db: AsyncSession, email: str) -> str:
    """管理员重置用户密码，返回新的临时密码。用户不存在→404。"""
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="用户不存在",
        )

    new_password = _generate_temp_password()
    user.password_hash = hash_password(new_password)
    await db.commit()
    logger.info("管理员重置密码: email=%s", email)
    return new_password


async def initiate_password_reset(db: AsyncSession, email: str) -> str | None:
    """P1-23 方案 B：发起密码重置流程。

    - 用户存在：生成 reset token（JWT, type=reset），通过 EmailSender 发送重置邮件
      - 开发环境（EMAIL_PROVIDER=log）：LogEmailSender 写日志，token 仍可在日志提取
      - 生产环境（EMAIL_PROVIDER=smtp）：SmtpEmailSender 发送真实邮件
    - 用户不存在：静默返回 None（不泄露用户是否存在，防止枚举攻击）

    返回 reset token（保留以便日志记录和单元测试提取），用户不存在时返回 None。

    Task 1.2 改造点：
    - 把"发邮件"动作委托给 EmailSender 抽象层
    - 保留 auth_service 的业务日志（reset_token=xxx），与现有 test_password_reset.py 兼容
    - LogEmailSender 内部也会写 services.email_sender 日志（含完整重置链接）
    """
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if user is None:
        # 防止用户枚举：不报错，不生成 token
        logger.info("密码重置请求: email=%s 用户不存在（静默忽略）", email)
        return None

    token = create_reset_token({"sub": str(user.id)})

    # 业务日志：保留 reset_token 写入，开发环境从日志提取 token 联调（兼容现有测试）
    # 生产环境若 EMAIL_PROVIDER=smtp，应改为只记录 token 前缀，避免 token 泄露到日志文件
    # 当前实现：日志始终写完整 token，方便排查；上线前可在 SmtpEmailSender 启用时
    # 改为 logger.info("密码重置请求: email=%s (邮件已发送)", email)
    logger.info(
        "密码重置请求: email=%s reset_token=%s (有效期 %d 分钟)",
        email,
        token,
        30,  # 与 settings.RESET_TOKEN_EXPIRE_MINUTES 对齐
    )

    # 委托 EmailSender 发送邮件（log=写日志 / smtp=真实发邮件）
    # 失败不阻塞 API 返回 200，防止攻击者通过响应时间/异常判断用户是否存在
    try:
        sender = get_email_sender()
        sender.send_reset_email(to=email, token=token)
    except Exception:
        # 发送失败仅记录错误日志，不抛出（防止用户枚举 + 不影响 reset token 已生成）
        # 注意：开发环境 LogEmailSender 不会抛异常，这里主要兜底 SmtpEmailSender 网络故障
        logger.exception("密码重置邮件发送失败: email=%s", email)

    return token


async def complete_password_reset(db: AsyncSession, token: str, new_password: str) -> None:
    """P1-23 方案 B：完成密码重置。

    验证 reset token 并更新密码。token 无效/过期/已使用→400。
    验证步骤：
    1. decode JWT（过期/签名错误→400）
    2. 校验 type==reset（防止 access/refresh token 误用）
    3. 校验未撤销（一次性使用）
    4. 校验用户仍存在
    5. 更新密码 hash
    6. 撤销 token jti（防止重放）
    """
    payload = decode_token(token)
    if payload is None or payload.get("type") != "reset":
        logger.warning(
            "重置密码失败: 无效 token (type=%s)",
            payload.get("type") if payload else "decode_failed",
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="无效或过期的重置凭证",
        )

    if await is_token_revoked(payload.get("jti")):
        logger.warning("重置密码失败: token 已使用 (jti=%s)", payload.get("jti"))
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="重置凭证已使用，请重新申请",
        )

    user_id_str = payload.get("sub")
    if user_id_str is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="无效的重置凭证",
        )
    try:
        user_id = int(user_id_str)
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="无效的重置凭证",
        )

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="用户不存在",
        )

    user.password_hash = hash_password(new_password)
    await db.commit()

    # 一次性使用：撤销该 reset token
    await revoke_token(payload.get("jti"))

    logger.info("密码重置成功: user_id=%s", user_id)
