from __future__ import annotations

#   核心基础设施模块：集中管理配置、日志、限流和运行时状态。

from functools import lru_cache

try:
    from pydantic_settings import BaseSettings, SettingsConfigDict
except ImportError:  # pragma: no cover - keeps source importable before install
    from pydantic import BaseModel

    #  模块中的核心类型，封装相关状态和行为。
    class BaseSettings(BaseModel):  # type: ignore[no-redef]
        model_config = {"extra": "ignore"}

    SettingsConfigDict = dict  # type: ignore[misc,assignment]


#  模块中的核心类型，封装相关状态和行为。
class Settings(BaseSettings):
    app_env: str = "development"
    api_addr: str = "0.0.0.0:8080"
    database_url: str = "sqlite+aiosqlite:///./backend_py.db"
    database_schema_mode: str = "auto"
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
    image_embedding_provider: str = "dashscope"
    image_embedding_base_url: str = "https://dashscope.aliyuncs.com"
    image_embedding_api_key: str = ""
    image_embedding_model: str = "qwen3-vl-embedding"
    image_embedding_dimension: int = 1536
    image_embedding_timeout_seconds: float = 20.0
    file_storage_provider: str = "local"
    file_storage_local_dir: str = "./backend_py_uploads"
    avatar_upload_root: str = "./uploads/avatar"
    minio_endpoint: str = "127.0.0.1:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_bucket: str = "xzxg-shop"
    rag_vector_enabled: bool = False
    rag_vector_provider: str = "none"
    milvus_address: str = "http://127.0.0.1:19530"
    milvus_token: str = ""
    milvus_knowledge_collection: str = "knowledge_text_chunks"
    milvus_image_collection: str = "product_image_vectors_v1536"
    embedding_base_url: str = ""
    embedding_api_key: str = ""
    embedding_model: str = "text-embedding-v4"
    embedding_provider: str = "dashscope"
    embedding_dimension: int = 128
    product_rerank_enabled: bool = True
    product_rerank_model_enabled: bool = True
    product_rerank_base_url: str = "https://dashscope.aliyuncs.com"
    product_rerank_api_key: str = ""
    product_rerank_model: str = "qwen3-vl-rerank"
    product_rerank_max_candidates: int = 80
    product_rerank_min_score: float = 0.50
    product_rerank_max_score_delta: float = 0.12
    product_rerank_fallback_rule_enabled: bool = True
    nacos_addr: str = ""
    nacos_namespace: str = ""
    nacos_group: str = "XZXG_SHOP"
    nacos_data_id: str = "xzxg-shop-app-config.json"
    nacos_prompt_data_id: str = "xzxg-shop-prompt-config.json"
    nacos_username: str = ""
    nacos_password: str = ""
    runtime_config_refresh_seconds: float = 30.0
    speech_realtime_enabled: bool = False
    speech_tts_enabled: bool = False
    speech_tts_provider: str = "xunfei"
    speech_tts_voice: str = "xiaoyan"
    speech_tts_max_text_chars: int = 500
    speech_tts_timeout_seconds: float = 20.0
    xunfei_app_id: str = ""
    xunfei_api_key: str = ""
    xunfei_api_secret: str = ""
    xunfei_rtasr_base_url: str = "wss://office-api-ast-dx.iflyaisol.com"
    xunfei_rtasr_path: str = "/ast/communicate/v1"
    xunfei_tts_enabled: bool = False
    xunfei_tts_app_id: str = ""
    xunfei_tts_api_key: str = ""
    xunfei_tts_api_secret: str = ""
    xunfei_tts_base_url: str = "wss://tts-api.xfyun.cn/v2/tts"
    xunfei_tts_voice: str = "xiaoyan"
    xunfei_tts_audio_encoding: str = "lame"
    xunfei_tts_max_runes: int = 800
    xunfei_tts_timeout_seconds: float = 20.0
    doubao_tts_app_id: str = ""
    doubao_tts_api_key: str = ""
    doubao_tts_base_url: str = "https://openspeech.bytedance.com/api/v1/tts"
    doubao_tts_cluster: str = "volcano_tts"
    doubao_tts_voice: str = "BV700_streaming"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    #     cors_origins：完成本模块的一步处理，并把结果返回给调用方。
    @property
    def cors_origins(self) -> list[str]:
        if self.cors_allowed_origins.strip() == "*":
            return ["*"]
        return [item.strip() for item in self.cors_allowed_origins.split(",") if item.strip()]


#  获取 get_settings：完成本模块的一步处理，并把结果返回给调用方。
@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
