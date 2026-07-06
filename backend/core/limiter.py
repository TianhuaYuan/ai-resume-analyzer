"""API 限流器实例。main.py 初始化，router 装饰器导入使用。"""
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address, default_limits=["60/minute"])
