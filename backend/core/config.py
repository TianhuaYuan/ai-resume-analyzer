from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


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

    model_config = SettingsConfigDict(
        env_file=".env",
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