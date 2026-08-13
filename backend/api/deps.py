from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.database import get_db
from core.security import decode_token, extract_token_from_request, is_token_revoked
from models.user import User


async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> User:
    """双模取 token（Authorization Bearer 或 HttpOnly Cookie），解码校验，查库返回 User。

    - 无效/过期 → 401
    - 已被撤销（SEC-005，登出/改密后 jti 进黑名单）→ 401
    - 既无 Bearer 也无 Cookie → 401
    """
    token = extract_token_from_request(request)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="缺少认证凭证",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = decode_token(token)
    if payload is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="无效或过期的凭证")

    if payload.get("type") != "access":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="凭证类型无效")

    # 撤销名单校验
    if await is_token_revoked(payload.get("jti")):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="凭证已失效，请重新登录",
            headers={"WWW-Authenticate": "Bearer"},
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

    # S1-T8: 改密后旧 token 失效（iat < password_changed_at）
    # 注意：JWT iat 只有秒级精度，比较时需截断 password_changed_at 到秒级
    if user.password_changed_at is not None:
        iat = payload.get("iat")
        if iat is not None:
            from datetime import datetime, timezone
            iat_dt = datetime.fromtimestamp(iat, tz=timezone.utc)
            pwd_changed = user.password_changed_at
            # SQLite 可能返回 naive datetime，统一视为 UTC
            if pwd_changed.tzinfo is None:
                pwd_changed = pwd_changed.replace(tzinfo=timezone.utc)
            # 截断到秒级，与 iat 精度对齐
            pwd_changed = pwd_changed.replace(microsecond=0)
            if iat_dt < pwd_changed:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="密码已修改，请重新登录",
                    headers={"WWW-Authenticate": "Bearer"},
                )

    return user


async def require_admin(
    current_user: User = Depends(get_current_user),
) -> User:
    """校验当前用户是否为管理员，非管理员返回 403。

    管理员判定：settings.ADMIN_EMAILS 列表中包含用户邮箱。
    """
    admin_emails_setting = settings.ADMIN_EMAILS
    if isinstance(admin_emails_setting, str):
        admin_emails = [e.strip() for e in admin_emails_setting.split(",") if e.strip()]
    else:
        admin_emails = list(admin_emails_setting)

    if not current_user.is_admin and current_user.email not in admin_emails:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="需要管理员权限",
        )
    return current_user
