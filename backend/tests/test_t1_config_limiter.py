"""T2: config 10 项新配置 + limiter Redis storage + .env.example 同步。"""

import pytest


# ═══════════════════════════════════════════════════════════
# RED: 新配置项应存在且有默认值
# ═══════════════════════════════════════════════════════════
def test_react_config_defaults():
    """React Agent 配置项有正确默认值。"""
    from core.config import settings

    assert settings.REACT_MAX_TOOL_ROUNDS == 6
    assert settings.REACT_MAX_ITER_TOKENS == 16000
    assert settings.REACT_TOOL_RESULT_MAX_CHARS == 2000
    assert settings.REACT_KEEP_LAST_ROUNDS == 4


def test_thinking_config_defaults():
    """Thinking 配置项有正确默认值。"""
    from core.config import settings

    assert settings.THINKING_ENABLED is True
    assert settings.THINKING_EFFORT == "high"


def test_builder_config_defaults():
    """Builder 配置项有正确默认值。"""
    from core.config import settings

    assert settings.TEMPLATE_DIR == "backend/templates"
    assert settings.BUILDER_PARSE_MODEL == ""


def test_rate_limit_ask_agent():
    """/ask/agent 有独立限流配置。"""
    from core.config import settings

    assert settings.RATE_LIMIT_ASK_AGENT == "8/minute"


# ═══════════════════════════════════════════════════════════
# RED: limiter 应配置 Redis storage + fallback
# ═══════════════════════════════════════════════════════════
def test_limiter_uses_redis_storage():
    """Limiter 使用 Redis 作为存储后端。"""
    from core.limiter import limiter

    # slowapi 的 Limiter 在配置了 storage_uri 时会用 Redis
    assert limiter._storage is not None
    assert limiter._in_memory_fallback_enabled is True


# ═══════════════════════════════════════════════════════════
# RED: .env.example 应包含新配置项
# ═══════════════════════════════════════════════════════════
def test_env_example_contains_new_configs():
    """.env.example 包含所有新配置项。"""
    import os

    env_example_path = os.path.join(
        os.path.dirname(__file__), "..", ".env.example"
    )
    with open(env_example_path, "r", encoding="utf-8") as f:
        content = f.read()

    required_keys = [
        "REACT_MAX_TOOL_ROUNDS",
        "REACT_MAX_ITER_TOKENS",
        "REACT_TOOL_RESULT_MAX_CHARS",
        "REACT_KEEP_LAST_ROUNDS",
        "THINKING_ENABLED",
        "THINKING_EFFORT",
        "TEMPLATE_DIR",
        "BUILDER_PARSE_MODEL",
        "RATE_LIMIT_ASK_AGENT",
    ]
    for key in required_keys:
        assert key in content, f"{key} missing from .env.example"
