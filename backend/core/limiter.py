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


limiter = Limiter(key_func=get_real_ip, default_limits=[settings.RATE_LIMIT_DEFAULT])

