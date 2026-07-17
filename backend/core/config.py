import logging
import os

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

# APP_ENV 控制加载哪个 .env 文件：dev → .env.dev, test → .env.test, prod → .env.prod
# 未设置时默认 dev，与现有开发习惯兼容
_APP_ENV = os.getenv("APP_ENV", "dev")


class Settings(BaseSettings):
    CHAT_API_KEY: str
    CHAT_BASE_URL: str
    CHAT_MODEL: str

    EMBEDDING_API_KEY: str
    EMBEDDING_BASE_URL: str
    EMBEDDING_MODEL: str

    RERANK_API_KEY: str
    RERANK_BASE_URL: str
    RERANK_MODEL: str

    # ── Judge 评估模型（阶段7 新增，独立于业务 Chat 模型）──
    # ⚠️ Judge 用 DeepSeek，与业务 Chat（Xiaomi MiMo）是两套独立模型/密钥。
    # 这样能消除「同模型既答题又打分」的自偏好偏差。默认关闭，避免未配置即启动失败。
    JUDGE_API_KEY: str = ""
    JUDGE_BASE_URL: str = "https://api.deepseek.com/v1"
    JUDGE_MODEL: str = "deepseek-chat"
    JUDGE_TEMPERATURE: float = 0.0
    # 是否启用 DeepSeek Judge：true 走 DeepSeek；false 时 judge() 直接报错，由调用方决定回退策略。
    JUDGE_ENABLED: bool = False
    # 极端降级开关：仅当 DeepSeek 不可用且必须跑评估时，允许回退用业务 Chat 模型打分。
    # 默认关闭——因为回退会让「同模型自评」偏差回归，能不用就不用。
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
    # 阶段9 SEC-003：refresh 端点单独限流（刷新凭证是高频爆破目标）
    RATE_LIMIT_REFRESH: str = "5/minute"

    # ── 请求体大小限制（阶段9 SEC-013）──
    # 防止超大请求体打满内存（DoS）。与上传上限解耦：上传走 multipart 单独校验。
    MAX_REQUEST_BODY_MB: int = 10

    # ── Cookie 安全配置（阶段9 SEC-004 HttpOnly Cookie）──
    # 生产环境强制 Secure；开发环境（http）关掉以便本地联调。
    COOKIE_SECURE: bool = True
    COOKIE_SAMESITE: str = "lax"  # lax 兼容 top-level 导航，又挡第三方
    AUTH_COOKIE_NAME: str = "access_token"
    REFRESH_COOKIE_NAME: str = "refresh_token"

    # ── LLM 输出 PII 脱敏开关（阶段9 SEC-010）──
    # 默认关闭：简历分析本就需要回显候选人手机/邮箱等 PII，盲目脱敏会破坏产品价值。
    # 开启后仅对"高置信度且非检索来源"的 PII 脱敏，属合规可选项，由部署方决定。
    REDACT_PII_OUTPUT: bool = False

    # ── MCP 配置 ──
    MCP_SERVER_URL: str = "http://127.0.0.1:8000/mcp"
    MCP_TOKEN: str = ""  # MCP Server 认证 token，为空则不认证

    # ── 监控配置 ──
    METRICS_TOKEN: str = ""  # Prometheus /metrics 抓取所需的 Bearer token，生产环境必填

    # ── 运行时配置 ──
    UVICORN_WORKERS: int = 4  # 生产环境 worker 数，可通过环境变量覆盖

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


settings = Settings()


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