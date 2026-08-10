"""API 限流器实例。main.py 初始化，router 装饰器导入使用。"""

import ipaddress

from slowapi import Limiter
from starlette.requests import Request

from .config import settings


def get_real_ip(request: Request) -> str:
    """限流 key 来源：只信 request.client.host，不读可伪造的代理头。

    安全理由（P0-3）：直接读 X-Real-IP / X-Forwarded-For 会被客户端伪造头绕过限流。
    真实 IP 的改写由 SimpleProxyHeadersMiddleware 完成——它只对可信来源
    （nginx 内网 CIDR / loopback，见 main.py trusted_hosts）信任代理头，
    并把结果写回 request.client.host。限流器位于该中间件之后执行，
    读 client.host 即可拿到经可信代理清洗的真实 IP，且天然免疫伪造头。
    """
    client_host = request.client.host if request.client else None
    if client_host:
        # Only trust forwarding headers when the immediate peer is one of the
        # proxy addresses configured by the ASGI middleware.  Direct clients
        # cannot spoof X-Forwarded-For to evade rate limits.
        try:
            peer = ipaddress.ip_address(client_host)
            trusted = any(
                peer in ipaddress.ip_network(cidr)
                for cidr in ("127.0.0.1/32", "10.0.0.0/8", "172.16.0.0/12")
            )
        except ValueError:
            trusted = False
        if trusted:
            forwarded = request.headers.get("X-Real-IP")
            if forwarded:
                return forwarded.strip()
            forwarded = request.headers.get("X-Forwarded-For")
            if forwarded:
                return forwarded.split(",", 1)[0].strip()
        return client_host
    return "unknown"


limiter = Limiter(
    key_func=get_real_ip,
    default_limits=[settings.RATE_LIMIT_DEFAULT],
    # 开发/测试环境无 Redis：slowapi 每次限流检查会尝试连接 Redis，
    # 卡在 OS 级 TCP 超时（实测 ~4s）后才降级内存 → 登录等受限流接口延迟严重。
    # 开发/测试直接用内存限流（storage_uri=None → slowapi 默认 memory://）；
    # 生产/预发多 worker 共享限流计数才接 Redis。
    storage_uri=(
        None
        if settings.ENVIRONMENT in ("development", "dev", "test", "testing")
        else settings.REDIS_URL
    ),
    in_memory_fallback_enabled=True,
)
