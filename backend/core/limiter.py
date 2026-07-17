"""API 限流器实例。main.py 初始化，router 装饰器导入使用。"""
from slowapi import Limiter
from slowapi.util import get_remote_address

from .config import settings

limiter = Limiter(key_func=get_remote_address, default_limits=[settings.RATE_LIMIT_DEFAULT])
#改进方案：redis 滑动窗口