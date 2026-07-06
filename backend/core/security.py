"""JWT 编解码 + bcrypt 密码哈希。"""
import logging
from datetime import datetime, timedelta, timezone

import bcrypt
from jose import JWTError, jwt

from .config import settings

logger = logging.getLogger(__name__)


def hash_password(plain: str) -> str:
    """bcrypt 加盐哈希"""
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())


def _create_token(data: dict, delta: timedelta, token_type: str) -> str:
    """签发 JWT，注入 exp 和 type"""
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + delta
    to_encode.update({"exp": expire, "type": token_type})
    return jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def create_access_token(data: dict) -> str:
    """生成 access token（短期），payload 需含 sub"""
    return _create_token(data, timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES), "access")


def create_refresh_token(data: dict) -> str:
    """生成 refresh token（长期）"""
    return _create_token(data, timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS), "refresh")


def decode_token(token: str) -> dict | None:
    """解码 JWT，过期或无效返回 None"""
    try:
        return jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    except JWTError as e:
        logger.warning("JWT decode failed: %s", e)
        return None
