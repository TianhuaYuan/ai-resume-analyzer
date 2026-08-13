import logging
import secrets
import string

from fastapi import HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.security import (
    hash_password,
    verify_password,
    create_access_token,
    create_refresh_token,
    decode_token,
    is_token_revoked,
    revoke_token,
)
from models.user import User
from schemas.auth import RegisterRequest, TokenResponse
from services.verification_service import verify_code

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
    data = {"sub": str(user.id), "username": user.username, "email": user.email}
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

    # S1-T8: 改密后旧 refresh_token 失效（iat < password_changed_at）
    # 注意：JWT iat 只有秒级精度，比较时需截断到秒级
    if user.password_changed_at is not None:
        iat = payload.get("iat")
        if iat is not None:
            from datetime import datetime, timezone
            iat_dt = datetime.fromtimestamp(iat, tz=timezone.utc)
            pwd_changed = user.password_changed_at
            if pwd_changed.tzinfo is None:
                pwd_changed = pwd_changed.replace(tzinfo=timezone.utc)
            pwd_changed = pwd_changed.replace(microsecond=0)
            if iat_dt < pwd_changed:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="密码已修改，请重新登录",
                )

    # 撤销旧 refresh token（TTL 对齐 refresh 生命周期，防 30 分钟后撤销失效可复用）
    await revoke_token(payload.get("jti"), expire_seconds=settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400)

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
    from datetime import datetime, timezone

    user.password_changed_at = datetime.now(timezone.utc)
    await db.commit()
    logger.info("管理员重置密码: email=%s", email)
    return new_password


async def reset_password_by_verification(
    db: AsyncSession, email: str, new_password: str
) -> bool:
    """新流程：验证码通过后直接修改密码（无需邮件链接）。

    - 用户存在 → 更新密码 hash，返回 True
    - 用户不存在 → 静默返回 False（防用户枚举）

    调用方需先验证 verification_code（保证调用本函数时验证码已通过）。
    """
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if user is None:
        logger.info("密码重置（验证码）: email=%s 用户不存在（静默忽略）", email)
        return False

    user.password_hash = hash_password(new_password)
    from datetime import datetime, timezone

    user.password_changed_at = datetime.now(timezone.utc)
    await db.commit()
    logger.info("密码重置成功（验证码）: user_id=%s", user.id)
    return True


async def change_password(
    db: AsyncSession,
    user: User,
    mode: str,
    new_password: str,
    old_password: str | None = None,
    verification_code: str | None = None,
) -> bool:
    """修改密码。支持旧密码验证和邮箱验证码两种方式。

    S1-T8: 改密后更新 password_changed_at，使旧 token（iat < password_changed_at）失效。

    Args:
        db: 数据库会话
        user: 当前用户
        mode: "password" 旧密码验证 / "code" 验证码验证
        new_password: 新密码
        old_password: 旧密码（mode=password时必填）
        verification_code: 验证码（mode=code时必填）

    Raises:
        HTTPException: 验证失败时抛出
    """
    from datetime import datetime, timezone

    if mode == "password":
        if not old_password:
            raise HTTPException(status_code=400, detail="请输入旧密码")
        if not verify_password(old_password, user.password_hash):
            raise HTTPException(status_code=400, detail="旧密码错误")
    elif mode == "code":
        if not verification_code:
            raise HTTPException(status_code=400, detail="请输入验证码")
        if not await verify_code(user.email, verification_code):
            raise HTTPException(status_code=400, detail="验证码无效或已过期")

    user.password_hash = hash_password(new_password)
    user.password_changed_at = datetime.now(timezone.utc)
    await db.commit()
    logger.info("密码修改成功: user_id=%s, mode=%s", user.id, mode)
    return True


async def change_email(
    db: AsyncSession,
    user: User,
    new_email: str,
    verification_code: str,
) -> bool:
    """修改邮箱。

    Args:
        db: 数据库会话
        user: 当前用户
        new_email: 新邮箱
        verification_code: 邮箱验证码

    Raises:
        HTTPException: 验证失败或邮箱冲突时抛出
    """
    if not await verify_code(new_email, verification_code):
        raise HTTPException(status_code=400, detail="验证码无效或已过期")

    if new_email == user.email:
        raise HTTPException(status_code=400, detail="新邮箱不能与当前邮箱相同")

    # 检查新邮箱是否已被其他用户使用
    result = await db.execute(select(User).where(User.email == new_email))
    existing = result.scalar_one_or_none()
    if existing is not None and existing.id != user.id:
        raise HTTPException(status_code=409, detail="该邮箱已被绑定")

    user.email = new_email
    await db.commit()
    logger.info("邮箱修改成功: user_id=%s", user.id)
    return True


async def change_username(
    db: AsyncSession,
    user: User,
    new_username: str,
) -> bool:
    """修改用户名。

    Args:
        db: 数据库会话
        user: 当前用户
        new_username: 新用户名

    Raises:
        HTTPException: 用户名冲突时抛出
    """
    if new_username == user.username:
        raise HTTPException(status_code=400, detail="新用户名不能与当前用户名相同")

    result = await db.execute(select(User).where(User.username == new_username))
    existing = result.scalar_one_or_none()
    if existing is not None and existing.id != user.id:
        raise HTTPException(status_code=409, detail="该用户名已被使用")

    user.username = new_username
    await db.commit()
    logger.info("用户名修改成功: user_id=%s", user.id)
    return True
