import logging
import os
import sys

from pydantic import ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

# APP_ENV 控制加载哪个 .env 文件：dev → .env.dev, test → .env.test, staging → .env.staging
_APP_ENV = os.getenv("APP_ENV", "dev")


class Settings(BaseSettings):
    APP_ENV: str = "dev"

    CHAT_API_KEY: str
    CHAT_BASE_URL: str
    CHAT_MODEL: str

    EMBEDDING_API_KEY: str
    EMBEDDING_BASE_URL: str
    EMBEDDING_MODEL: str

    RERANK_API_KEY: str
    RERANK_BASE_URL: str
    RERANK_MODEL: str

    JUDGE_API_KEY: str = ""
    JUDGE_BASE_URL: str = "https://api.deepseek.com/v1"
    JUDGE_MODEL: str = "deepseek-v4-flash"
    JUDGE_TEMPERATURE: float = 0.0
    JUDGE_ENABLED: bool = True
    JUDGE_FALLBACK_TO_CHAT: bool = False

    DATABASE_URL: str
    CHROMA_PERSIST_DIR: str = "./chroma_data"

    JWT_SECRET_KEY: str
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    CORS_ORIGINS: str = "http://localhost:5173,http://localhost:5174"
    LOG_LEVEL: str = "INFO"

    UPLOAD_DIR: str = "./uploads"
    MAX_UPLOAD_SIZE_MB: int = 10  # 单文件最大 10MB

    # ── 环境配置 ──
    ENVIRONMENT: str = "development"  # development / staging / production

    # ── 限流配置 ──
    RATE_LIMIT_DEFAULT: str = "60/minute"
    RATE_LIMIT_LOGIN: str = "10/minute"
    RATE_LIMIT_REGISTER: str = "5/minute"
    RATE_LIMIT_ASK: str = "20/minute"
    # refresh 端点单独限流（刷新凭证是高频爆破目标）
    RATE_LIMIT_REFRESH: str = "5/minute"
    # P1-23: 忘记密码端点限流（爆破/滥用防御，3 次/分钟）
    RATE_LIMIT_PASSWORD_RESET: str = "3/minute"

    # 防止超大请求体打满内存（DoS）。与上传上限解耦：上传走 multipart 单独校验。
    MAX_REQUEST_BODY_MB: int = 10

    # 生产环境强制 Secure；开发环境（http）关掉以便本地联调。
    COOKIE_SECURE: bool = True
    COOKIE_SAMESITE: str = "lax"  # lax 兼容 top-level 导航，又挡第三方
    AUTH_COOKIE_NAME: str = "access_token"
    REFRESH_COOKIE_NAME: str = "refresh_token"

    # 默认关闭：简历分析本就需要回显候选人手机/邮箱等 PII，盲目脱敏会破坏产品价值。
    REDACT_PII_OUTPUT: bool = False

    MCP_SERVER_URL: str = "http://127.0.0.1:8000/mcp"
    MCP_TOKEN: str = ""  # MCP Server 认证 token，为空则不认证

    # Redis 配置
    REDIS_URL: str = "redis://localhost:6379/0"

    # 监控配置
    METRICS_TOKEN: str = ""  # Prometheus /metrics 抓取所需的 Bearer token，生产环境必填

    # 运行时配置
    UVICORN_WORKERS: int = 4  # 生产环境 worker 数，可通过环境变量覆盖

    # P1-23: 管理员邮箱列表（逗号分隔），拥有管理员重置密码等权限
    ADMIN_EMAILS: str = ""

    # ── Task 1.2: 邮件发送配置 ──
    # EMAIL_PROVIDER: log（开发默认，写日志）/ smtp（生产，真实发邮件）
    EMAIL_PROVIDER: str = "log"
    SMTP_HOST: str = ""
    SMTP_PORT: int = 465
    SMTP_USERNAME: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_USE_TLS: bool = False  # False=SMTP_SSL(465)，True=SMTP+starttls(587)
    SMTP_FROM: str = ""  # 发件人地址，如 noreply@example.com
    # 前端基础 URL，用于拼接密码重置链接（如 http://localhost:5173）
    FRONTEND_BASE_URL: str = "http://localhost:5173"

    # ── RAG 共享常量 ──
    DEFAULT_HYBRID_TOP_K: int = 20
    DEFAULT_RERANK_TOP_K: int = 5
    DEFAULT_GENERATE_TEMPERATURE: float = 0.3
    MCP_HTTP_TIMEOUT_TOTAL: int = 30  # MCP 远端 LLM 调用总超时（秒）
    MCP_HTTP_TIMEOUT_CONNECT: int = 10  # MCP 远端 LLM 连接超时（秒）

    model_config = SettingsConfigDict(
        env_file=f".env.{_APP_ENV}",
        env_file_encoding="utf-8",
        extra="forbid",
        case_sensitive=True,
    )

    @field_validator("JWT_SECRET_KEY")
    @classmethod
    def _check_secret_length(cls, v: str) -> str:
        if len(v) < 32:
            raise ValueError("JWT_SECRET_KEY must be at least 32 characters")
        return v


# P3-12: 包装 Settings() 实例化，捕获 ValidationError 给出友好中文提示
# 原行为：pydantic 校验失败直接抛 ValidationError，错误信息含 traceback 但缺：
#   - 当前 APP_ENV 对应哪个 .env 文件
#   - 哪个字段缺失/不合法
#   - 解决方向
# 修复后：输出友好错误后重新抛出原始异常，保留 traceback 便于调试
def _format_settings_error(e: ValidationError, app_env: str) -> str:
    """格式化 Settings 校验错误为友好中文提示。独立函数便于测试。"""
    env_file = f".env.{app_env}"
    failed_fields = [err["loc"][0] for err in e.errors() if err.get("loc")]
    fields_str = ", ".join(failed_fields) if failed_fields else "（详见上方错误）"
    return (
        f"\n{'=' * 60}\n"
        f"❌ 配置加载失败：APP_ENV={app_env!r}，期望从 {env_file} 读取配置\n"
        f"失败字段：{fields_str}\n"
        f"解决方向：\n"
        f"  1. 检查 backend/{env_file} 是否存在并包含上述字段\n"
        f"  2. 检查 APP_ENV 环境变量是否正确（dev/test/staging/prod）\n"
        f"  3. 检查字段值是否合法（如 JWT_SECRET_KEY 至少 32 字符）\n"
        f"{'=' * 60}\n"
    )


try:
    settings = Settings()
except ValidationError as e:
    _hint = _format_settings_error(e, _APP_ENV)
    print(_hint, file=sys.stderr)
    logger.error("Settings 加载失败：APP_ENV=%s", _APP_ENV)
    raise


# 启动期必须齐全的关键配置（缺失则直接启动失败，避免带着错误配置跑起来）
_REQUIRED_NON_EMPTY = (
    "DATABASE_URL",
    "CHAT_API_KEY",
    "EMBEDDING_API_KEY",
    "RERANK_API_KEY",
    "JWT_SECRET_KEY",
)
# METRICS_TOKEN 仅在非开发环境强制，避免阻断本地开发；生产/预发缺失即启动失败
_PROD_ENVIRONMENTS = ("production", "staging")

def validate_required_settings() -> None:
    """校验关键环境变量/配置是否齐全。

    缺失则在启动期 raise 清晰错误，配合 lifespan 调用实现 fail-fast。
    METRICS_TOKEN 在生产/预发环境强制要求；开发环境不强制（本地无需配置即可起服务）。
    """
    missing = [name for name in _REQUIRED_NON_EMPTY if not getattr(settings, name, "").strip()]

    if settings.ENVIRONMENT in _PROD_ENVIRONMENTS and not settings.METRICS_TOKEN.strip():
        missing.append("METRICS_TOKEN")

    if missing:
        raise RuntimeError(
            "启动配置校验失败，缺少以下必要环境变量/配置："
            + ", ".join(missing)
            + "。请在对应 .env 文件中补齐后再启动服务。"
        )

    logger.info("配置校验通过：关键环境变量/配置齐全（ENVIRONMENT=%s）", settings.ENVIRONMENT)
