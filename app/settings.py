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
    openai_chat_model: str = Field(default="gpt-4o-mini", alias="OPENAI_CHAT_MODEL")
    openai_embed_model: str = Field(
        default="text-embedding-3-small", alias="OPENAI_EMBED_MODEL"
    )
    openai_vision_model: str = Field(default="gpt-4o-mini", alias="OPENAI_VISION_MODEL")

    qdrant_url: str = Field(default="http://localhost:6333", alias="QDRANT_URL")
    qdrant_api_key: str | None = Field(default=None, alias="QDRANT_API_KEY")
    qdrant_collection: str = Field(default="celine_docs", alias="QDRANT_COLLECTION")

    docs_uri: str = Field(default="s3://docs/", alias="DOCS_URI")
    docs_poll_interval_seconds: int = Field(
        default=60, alias="DOCS_POLL_INTERVAL_SECONDS"
    )

    s3_endpoint_url: str | None = Field(default=None, alias="S3_ENDPOINT_URL")
    s3_access_key_id: str | None = Field(default=None, alias="S3_ACCESS_KEY_ID")
    s3_secret_access_key: str | None = Field(default=None, alias="S3_SECRET_ACCESS_KEY")
    s3_region: str = Field(default="us-east-1", alias="S3_REGION")

    uploads_uri: str = Field(default="file:///data/uploads", alias="UPLOADS_URI")
    max_upload_mb: int = Field(default=25, alias="MAX_UPLOAD_MB")

    ingest_enable: bool = Field(default=True, alias="INGEST_ENABLE")
    ingest_force_reload_on_start: bool = Field(
        default=False, alias="INGEST_FORCE_RELOAD_ON_START"
    )
    manifest_path: str = Field(default="/data/manifest.json", alias="MANIFEST_PATH")

    chat_db_path: str = Field(
        default="/data/chat_history.sqlite3", alias="CHAT_DB_PATH"
    )

    oauth2_trust_headers: bool = Field(default=True, alias="OAUTH2_TRUST_HEADERS")
    oauth2_jwks_url: str | None = Field(default=None, alias="OAUTH2_JWKS_URL")
    oauth2_issuer: str | None = Field(default=None, alias="OAUTH2_ISSUER")
    oauth2_audience: str | None = Field(default="oauth2_proxy", alias="OAUTH2_AUDIENCE")
    oauth2_jwt_cookie_name: str | None = Field(
        default=None, alias="OAUTH2_JWT_COOKIE_NAME"
    )


settings = Settings()
