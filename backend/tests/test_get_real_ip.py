"""限流 key_func 应从反向代理头获取真实客户端 IP。

原 bug：使用 slowapi.util.get_remote_address 直接读 request.client.host，
在 nginx 反代后所有请求 IP 都是 127.0.0.1，导致全局限流而非按用户限流。
"""
from unittest.mock import Mock


from core.limiter import get_real_ip


def test_get_real_ip_prefers_x_real_ip():
    """X-Real-IP 存在时优先使用。"""
    request = Mock()
    request.headers = {"X-Real-IP": "203.0.113.5"}
    request.client = Mock(host="127.0.0.1")

    assert get_real_ip(request) == "203.0.113.5"


def test_get_real_ip_falls_back_to_x_forwarded_for():
    """无 X-Real-IP 时从 X-Forwarded-For 取第一个 IP。"""
    request = Mock()
    request.headers = {"X-Forwarded-For": "198.51.100.1, 10.0.0.1, 10.0.0.2"}
    request.client = Mock(host="127.0.0.1")

    assert get_real_ip(request) == "198.51.100.1"


def test_get_real_ip_falls_back_to_client_host():
    """无代理头时回退到 request.client.host。"""
    request = Mock()
    request.headers = {}
    request.client = Mock(host="192.168.1.100")

    assert get_real_ip(request) == "192.168.1.100"


def test_get_real_ip_no_client_returns_unknown():
    """request.client 为 None 时返回 unknown。"""
    request = Mock()
    request.headers = {}
    request.client = None

    assert get_real_ip(request) == "unknown"


def test_get_real_ip_x_forwarded_for_strips_whitespace():
    """X-Forwarded-For 的 IP 可能有空格，应 strip。"""
    request = Mock()
    request.headers = {"X-Forwarded-For": " 198.51.100.1 , 10.0.0.1"}
    request.client = Mock(host="127.0.0.1")

    assert get_real_ip(request) == "198.51.100.1"
