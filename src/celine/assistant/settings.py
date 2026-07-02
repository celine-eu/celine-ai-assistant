from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    app_env: str = Field(default="prod", alias="APP_ENV")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    openai_chat_model: str = Field(default="gpt-5.4-mini", alias="OPENAI_CHAT_MODEL")
    openai_embed_model: str = Field(
        default="text-embedding-3-small", alias="OPENAI_EMBED_MODEL"
    )
    openai_vision_model: str = Field(default="gpt-4o-mini", alias="OPENAI_VISION_MODEL")

    qdrant_url: str = Field(
        default="http://host.docker.internal:6333", alias="QDRANT_URL"
    )
    qdrant_api_key: str | None = Field(default=None, alias="QDRANT_API_KEY")
    qdrant_collection: str = Field(default="celine_docs", alias="QDRANT_COLLECTION")

    docs_poll_interval_seconds: int = Field(
        default=60, alias="DOCS_POLL_INTERVAL_SECONDS"
    )
    training_materials_path: str = Field(
        default="/workspace/repositories/celine-training-materials",
        alias="TRAINING_MATERIALS_PATH",
    )
    training_materials_repo_url: str = Field(
        default="", alias="TRAINING_MATERIALS_REPO_URL"
    )
    training_materials_ref: str = Field(
        default="origin/main", alias="TRAINING_MATERIALS_REF"
    )
    training_materials_sync_on_start: bool = Field(
        default=True, alias="TRAINING_MATERIALS_SYNC_ON_START"
    )

    uploads_uri: str = Field(default="file://./data/uploads", alias="UPLOADS_URI")
    max_upload_mb: int = Field(default=25, alias="MAX_UPLOAD_MB")

    ingest_enable: bool = Field(default=True, alias="INGEST_ENABLE")
    ingest_force_reload_on_start: bool = Field(
        default=False, alias="INGEST_FORCE_RELOAD_ON_START"
    )
    manifest_path: str = Field(default="/app/data/manifest.json", alias="MANIFEST_PATH")

    database_url: str = Field(
        default="postgresql+asyncpg://postgres:securepassword123@host.docker.internal:15432/ai_assistant",
        description="postgresql+asyncpg://user:pass@host:5432/dbname",
        alias="DATABASE_URL",
    )
    db_pool_size: int = Field(default=10, alias="DB_POOL_SIZE")
    db_max_overflow: int = Field(default=20, alias="DB_MAX_OVERFLOW")
    db_pool_timeout: int = Field(default=30, alias="DB_POOL_TIMEOUT")
    db_pool_recycle: int = Field(default=1800, alias="DB_POOL_RECYCLE")

    oauth2_trust_headers: bool = Field(default=True, alias="OAUTH2_TRUST_HEADERS")
    oauth2_jwks_url: str | None = Field(default=None, alias="OAUTH2_JWKS_URL")
    oauth2_issuer: str | None = Field(default=None, alias="OAUTH2_ISSUER")
    oauth2_audience: str | None = Field(default="oauth2_proxy", alias="OAUTH2_AUDIENCE")
    oauth2_jwt_cookie_name: str | None = Field(
        default=None, alias="OAUTH2_JWT_COOKIE_NAME"
    )

    admin_group: str = Field(default="admins", alias="ADMIN_GROUP")
    digital_twin_api_url: str | None = Field(
        default="http://172.17.0.1:8002",
        alias="DIGITAL_TWIN_API_URL",
    )
    datasets_api_url: str | None = Field(
        default="http://172.17.0.1:8001",
        alias="DATASETS_API_URL",
    )
    rec_registry_api_url: str | None = Field(
        default="http://172.17.0.1:8004",
        alias="REC_REGISTRY_API_URL",
    )

    max_tool_rounds: int = Field(default=6, alias="MAX_TOOL_ROUNDS")
    max_tool_result_chars: int = Field(default=8000, alias="MAX_TOOL_RESULT_CHARS")
    chat_history_limit: int = Field(default=20, alias="CHAT_HISTORY_LIMIT")
    chat_word_limit: int = Field(default=25000, alias="CHAT_WORD_LIMIT")
    chat_hot_messages: int = Field(default=6, alias="CHAT_HOT_MESSAGES")


settings = Settings()
