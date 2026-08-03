"""API 限流器实例。main.py 初始化，router 装饰器导入使用。"""

from slowapi import Limiter
from starlette.requests import Request

from .config import settings


def get_real_ip(request: Request) -> str:
    """从反向代理头中获取真实客户端 IP。

    优先级：X-Real-IP > X-Forwarded-For 第一个 > request.client.host > "unknown"。
    在 nginx 反代后，request.client.host 是 nginx 的 IP，必须读代理头才能拿到真实用户 IP。
    """
    x_real_ip = request.headers.get("X-Real-IP")
    if x_real_ip:
        return x_real_ip.strip()
    x_forwarded_for = request.headers.get("X-Forwarded-For")
    if x_forwarded_for:
        return x_forwarded_for.split(",")[0].strip()
    if request.client:
        return request.client.host
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

