import logging
import re
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import unquote

import bcrypt
import jwt
from jwt.exceptions import PyJWTError as JWTError

from .config import settings

logger = logging.getLogger(__name__)

_revoked_jtis: set[str] = set()


async def revoke_token(jti: str | None, expire_seconds: int | None = None) -> None:
    """把某个 jti 加入撤销名单（L1 内存 + L2 Redis 双层）。

    Args:
        jti: Token 唯一标识
        expire_seconds: Redis key TTL，默认对齐 access token 30 分钟
    """
    if not jti:
        return
    _revoked_jtis.add(jti)

    if expire_seconds is None:
        expire_seconds = settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60

    try:
        from core.redis_client import get_redis

        redis_client = await get_redis()
        if redis_client:
            await redis_client.set(f"revoked:{jti}", "1", ex=expire_seconds)
    except Exception:
        logger.warning("Redis revoke failed for jti=%s, in-memory only", jti)


async def is_token_revoked(jti: str | None) -> bool:
    """检查 jti 是否被撤销。L1 命中直接返回，L1 未命中查 Redis。"""
    if not jti:
        return False
    if jti in _revoked_jtis:
        return True

    try:
        from core.redis_client import get_redis

        redis_client = await get_redis()
        if redis_client:
            exists = await redis_client.exists(f"revoked:{jti}")
            if exists:
                _revoked_jtis.add(jti)
                return True
    except Exception:
        logger.warning("Redis check failed for jti=%s", jti)

    return False


def hash_password(plain: str) -> str:
    """bcrypt 加盐哈希"""
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())


def _create_token(data: dict, delta: timedelta, token_type: str) -> str:
    """签发 JWT，注入 exp / type / jti / iat。

    - jti：全局唯一卡号，供 SEC-005 撤销机制定位具体 token
    - iat：签发时间，便于审计与"早于某时刻的 token 失效"等策略
    """
    to_encode = data.copy()
    now = datetime.now(timezone.utc)
    expire = now + delta
    to_encode.update(
        {
            "exp": expire,
            "type": token_type,
            "jti": uuid.uuid4().hex,
            "iat": int(now.timestamp()),
        }
    )
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

_DEV_ENVIRONMENTS = {"development", "dev"}


def _cookie_secure() -> bool:
    """仅在生产/预发环境给 cookie 打 Secure 标记（开发 http 下不打，否则浏览器拒收）。"""
    return settings.COOKIE_SECURE and settings.ENVIRONMENT not in _DEV_ENVIRONMENTS


def set_auth_cookies(
    response,  # starlette.responses.Response
    access_token: str,
    refresh_token: str,
    *,
    access_max_age: int | None = None,
    refresh_max_age: int | None = None,
) -> None:
    """在响应上种下 access / refresh 两个 HttpOnly Cookie。"""
    response.set_cookie(
        key=settings.AUTH_COOKIE_NAME,
        value=access_token,
        httponly=True,
        secure=_cookie_secure(),
        samesite=settings.COOKIE_SAMESITE,
        path="/",
        max_age=access_max_age,
    )
    response.set_cookie(
        key=settings.REFRESH_COOKIE_NAME,
        value=refresh_token,
        httponly=True,
        secure=_cookie_secure(),
        samesite=settings.COOKIE_SAMESITE,
        path="/api/v1/auth",
        max_age=refresh_max_age,
    )


def clear_auth_cookies(response) -> None:
    """登出时清除两个认证 cookie。"""
    response.delete_cookie(settings.AUTH_COOKIE_NAME, path="/")
    response.delete_cookie(settings.REFRESH_COOKIE_NAME, path="/api/v1/auth")


def extract_token_from_request(request) -> str | None:
    """双模取 token：优先 Authorization: Bearer，其次 HttpOnly Cookie。
    保证既有 Bearer 前端零改动，同时支持更安全的 cookie 通道。
    """
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return request.cookies.get(settings.AUTH_COOKIE_NAME)

_INJECTION_PATTERNS = [
    re.compile(r"忽略.{0,6}之前|忽略.{0,6}以上|忽略.{0,6}前面|ignore\s+(all\s+)?(previous|prior|above)", re.IGNORECASE),
    re.compile(r"忘掉.{0,6}之前|disregard|forget\s+(all\s+)?(previous|prior|above|instructions)", re.IGNORECASE),
    re.compile(r"你(现在)?(变成|扮演|是)\s*.{0,12}(助手|模型|ai)|you\s+are\s+now", re.IGNORECASE),
    re.compile(r"系统提示|system\s*prompt|system\s*message", re.IGNORECASE),
    re.compile(r"开发者模式|developer\s*mode|jailbreak|越狱", re.IGNORECASE),
    re.compile(r"泄露.{0,4}(提示|指令|prompt)|reveal\s+(your\s+)?(prompt|instruction|system)", re.IGNORECASE),
    re.compile(r"###\s*(指令|instruction)|<\|system\|>|<system>", re.IGNORECASE),
    re.compile(r"重新开始|reset\s*context|清除.{0,4}上下文", re.IGNORECASE),
    re.compile(r"执行.{0,4}指令|execute\s+(my\s+)?(command|instruction)", re.IGNORECASE),
    re.compile(r"覆盖.{0,4}规则|override\s+(your\s+)?(rules|instructions)", re.IGNORECASE),
    re.compile(r"无视.{0,4}要求|ignore\s+(all\s+)?(rules|requirements)", re.IGNORECASE),
    re.compile(r"(不要|不用).{0,6}(遵守|遵循|管|理会)|do\s+not\s+follow", re.IGNORECASE),
    re.compile(r"跳过.{0,6}(指令|prompt|提示)|skip\s+(the\s+)?(instruction|prompt)", re.IGNORECASE),
]


def _normalize_text(text: str) -> str:
    """对输入文本做预处理，提升注入检测的鲁棒性。
    
    处理：
    1. URL 解码（处理 %E5%8B%BF%E7%95%A5 → 忽略）
    2. Unicode 标准化（处理同形字攻击，如 Cyrillic 'і' → Latin 'i'）
    3. 移除零宽字符（\u200b 等不可见字符）
    """
    if not text:
        return text
    result = text
    try:
        result = unquote(result)
    except Exception:
        pass
    result = result.replace("\u200b", "").replace("\u200c", "").replace("\u200d", "")
    result = result.replace("\uFEFF", "")
    return result


def detect_prompt_injection(text: str) -> tuple[bool, str | None]:
    """检测文本是否含提示注入话术。返回 (是否可疑, 命中原因)。
    
    P3-1 增强：支持 URL 编码、Unicode 同形字、零宽字符绕过检测。
    """
    if not text:
        return False, None
    normalized = _normalize_text(text)
    for pat in _INJECTION_PATTERNS:
        if pat.search(normalized):
            if normalized != text:
                return True, f"命中注入模式(预处理后): {pat.pattern[:40]}"
            return True, f"命中注入模式: {pat.pattern[:40]}"
    return False, None

_PII_PATTERNS = [
    (re.compile(r"(\+\d{1,3}([-\s]?\d){6,15})"), "[国际号码]"),
    (re.compile(r"(?<!\d)(1[3-9]\d{9})(?!\d)"), "[手机]"),
    (re.compile(r"(?<!\d)(0\d{2,3}[-\s]?\d{7,8})(?!\d)"), "[座机]"),
    (re.compile(r"(?<!\d)(\d{4}[-\s]\d{4})(?!\d)"), "[香港号码]"),
    (re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"), "[邮箱]"),
    (re.compile(r"(?<!\d)(\d{17}[\dXx])(?!\d)"), "[身份证]"),
    (re.compile(r"(?<!\d)(\d{16,19})(?!\d)"), "[银行卡]"),
]
def redact_pii(text: str) -> str:
    """对文本做 PII 打码，返回脱敏后文本。输入为空或非字符串则原样返回。"""
    if not text or not isinstance(text, str):
        return text
    result = text
    for pattern, mask in _PII_PATTERNS:
        result = pattern.sub(mask, result)
    return result
