from __future__ import annotations

from functools import lru_cache

try:
    from pydantic_settings import BaseSettings, SettingsConfigDict
except ImportError:  # pragma: no cover - keeps source importable before install
    from pydantic import BaseModel

    class BaseSettings(BaseModel):  # type: ignore[no-redef]
        model_config = {"extra": "ignore"}

    SettingsConfigDict = dict  # type: ignore[misc,assignment]


class Settings(BaseSettings):
    """应用配置：字段名会自动从环境变量读取，未提供时使用这里的默认值。"""
    app_env: str = "development"
    api_addr: str = "0.0.0.0:8080"
    database_url: str = "sqlite+aiosqlite:///./backend_py.db"
    run_migrations: bool = True
    seed_demo_data: bool = True
    auth_token_ttl_hours: int = 24
    cors_allowed_origins: str = "*"
    rate_limit_per_minute: int = 120
    redis_url: str = ""
    body_limit_bytes: int = 12 * 1024 * 1024
    ai_enabled: bool = False
    ai_base_url: str = ""
    ai_api_key: str = ""
    ai_small_model: str = ""
    ai_large_model: str = ""
    ai_timeout_seconds: float = 20.0
    image_embedding_provider: str = "local_histogram"
    image_embedding_base_url: str = "https://dashscope.aliyuncs.com"
    image_embedding_api_key: str = ""
    image_embedding_model: str = "qwen3-vl-embedding"
    image_embedding_dimension: int = 512
    image_embedding_timeout_seconds: float = 20.0
    file_storage_provider: str = "local"
    file_storage_local_dir: str = "./backend_py_uploads"
    minio_endpoint: str = "127.0.0.1:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_bucket: str = "xzxg-shop"
    rag_vector_enabled: bool = False
    rag_vector_provider: str = "none"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    @property
    def cors_origins(self) -> list[str]:
        """把逗号分隔的跨域来源转换为 FastAPI/CORS 中间件需要的列表。"""
        if self.cors_allowed_origins.strip() == "*":
            return ["*"]
        return [item.strip() for item in self.cors_allowed_origins.split(",") if item.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    # 配置对象在进程内只创建一次，避免每次请求都重新读取 .env 和环境变量。
    return Settings()
