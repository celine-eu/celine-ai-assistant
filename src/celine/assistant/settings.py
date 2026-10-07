from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import AliasChoices, Field, field_validator


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # The legacy name of the environment signal. Read only through `posture.py`,
    # after CELINE_ENV and ENVIRONMENT; its default is not a signal (unset is
    # hardened either way), and only the value `dev` relaxes anything.
    app_env: str = Field(default="prod", alias="APP_ENV")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    # Every model call goes to an OpenAI-compatible endpoint the deployment names. There
    # is no default: members' messages and the data the tools fetch for them go wherever
    # this points, so an unset value must not mean a vendor. To use OpenAI itself, say
    # `https://api.openai.com/v1`. See `llm.configuration_problems`.
    llm_base_url: str = Field(default="", alias="LLM_BASE_URL")
    llm_api_key: str = Field(default="", alias="LLM_API_KEY")
    llm_chat_model: str = Field(default="", alias="LLM_CHAT_MODEL")
    # Empty means the chat model, which is right for a multimodal model.
    llm_vision_model: str = Field(default="", alias="LLM_VISION_MODEL")
    # Embeddings are often served by a process of their own; empty means the chat
    # endpoint and its key.
    llm_embed_base_url: str = Field(default="", alias="LLM_EMBED_BASE_URL")
    llm_embed_api_key: str = Field(default="", alias="LLM_EMBED_API_KEY")
    llm_embed_model: str = Field(default="", alias="LLM_EMBED_MODEL")
    # The vector size the collection is created with. Empty means ask the model once.
    llm_embed_dimensions: int | None = Field(default=None, alias="LLM_EMBED_DIMENSIONS")

    # The most a single model call may generate, reasoning included on vLLM. Never off:
    # a thinking model can loop for tens of thousands of tokens on one question.
    llm_max_tokens: int = Field(default=4096, gt=0, alias="LLM_MAX_TOKENS")
    # Empty means none is sent, and the server applies the model's own recommended
    # sampling (vLLM reads it from the model's generation_config.json).
    llm_temperature: float | None = Field(
        default=None, ge=0, le=2, alias="LLM_TEMPERATURE"
    )

    @field_validator("llm_embed_dimensions", "llm_temperature", mode="before")
    @classmethod
    def _empty_is_unset(cls, value):
        # Charts render an unset value as an empty string.
        return None if value == "" else value

    # The names these settings had until 2026-10-01. Declared only so a leftover refuses
    # startup instead of looking configured while nothing reads it.
    removed_openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    removed_openai_chat_model: str = Field(default="", alias="OPENAI_CHAT_MODEL")
    removed_openai_embed_model: str = Field(default="", alias="OPENAI_EMBED_MODEL")
    removed_openai_vision_model: str = Field(default="", alias="OPENAI_VISION_MODEL")

    qdrant_url: str = Field(
        default="http://host.docker.internal:6333", alias="QDRANT_URL"
    )
    qdrant_api_key: str | None = Field(default=None, alias="QDRANT_API_KEY")
    # A prefix, not a collection: each community's knowledge base is the Qdrant alias
    # `<prefix>__<community_id>__<embedding fingerprint>`. See `kb_collections.py`.
    qdrant_collection: str = Field(default="celine_docs", alias="QDRANT_COLLECTION")

    # Where `celine-assistant kb sync` keeps its clones of git sources.
    kb_sources_dir: str = Field(default="./data/kb-sources", alias="KB_SOURCES_DIR")
    # Sync the registered git sources when the service starts.
    kb_sync_on_start: bool = Field(default=False, alias="KB_SYNC_ON_START")
    # A token for cloning private git sources over HTTPS, sent only to KB_GIT_TOKEN_HOST.
    # It reaches git as an environment-supplied header: never the command line, the
    # database, or the clone's `.git/config`. For GitHub, a fine-grained token with
    # read-only Contents on the source repositories.
    kb_git_token: str = Field(default="", alias="KB_GIT_TOKEN")
    kb_git_token_host: str = Field(default="github.com", alias="KB_GIT_TOKEN_HOST")

    # The organization type a REC carries in the token's `organization` claim, and the
    # groups inside it that manage its knowledge. Onboarding's policy uses the same.
    rec_organization_type: str = Field(default="rec", alias="REC_ORGANIZATION_TYPE")
    rec_manager_groups: list[str] = Field(
        default_factory=lambda: ["managers", "admins"], alias="REC_MANAGER_GROUPS"
    )

    # Read by nothing since 2026-10-02: knowledge sources are registered per community
    # with `celine-assistant kb source add`. Declared so a leftover is reported at
    # startup rather than looking configured.
    removed_training_materials_path: str = Field(
        default="", alias="TRAINING_MATERIALS_PATH"
    )
    removed_training_materials_repo_url: str = Field(
        default="", alias="TRAINING_MATERIALS_REPO_URL"
    )
    removed_training_materials_ref: str = Field(
        default="", alias="TRAINING_MATERIALS_REF"
    )
    removed_training_materials_sync_on_start: str = Field(
        default="", alias="TRAINING_MATERIALS_SYNC_ON_START"
    )
    removed_manifest_path: str = Field(default="", alias="MANIFEST_PATH")
    removed_ingest_enable: str = Field(default="", alias="INGEST_ENABLE")
    removed_ingest_force_reload_on_start: str = Field(
        default="", alias="INGEST_FORCE_RELOAD_ON_START"
    )
    removed_docs_poll_interval_seconds: str = Field(
        default="", alias="DOCS_POLL_INTERVAL_SECONDS"
    )

    uploads_uri: str = Field(default="file://./data/uploads", alias="UPLOADS_URI")
    max_upload_mb: int = Field(default=25, alias="MAX_UPLOAD_MB")

    database_url: str = Field(
        default="postgresql+asyncpg://postgres:securepassword123@host.docker.internal:15432/ai_assistant",
        description="postgresql+asyncpg://user:pass@host:5432/dbname",
        alias="DATABASE_URL",
    )
    db_pool_size: int = Field(default=10, alias="DB_POOL_SIZE")
    db_max_overflow: int = Field(default=20, alias="DB_MAX_OVERFLOW")
    db_pool_timeout: int = Field(default=30, alias="DB_POOL_TIMEOUT")
    db_pool_recycle: int = Field(default=1800, alias="DB_POOL_RECYCLE")

    # Off by default: an identity is established from a verified JWT. The unverified
    # `x-auth-request-*` headers are trusted only where the operator has explicitly
    # opted in AND the network guarantees the proxy alone can set them (see ADR-0003).
    oauth2_trust_headers: bool = Field(default=False, alias="OAUTH2_TRUST_HEADERS")
    # A configured trust anchor is required to verify a token. `OAUTH2_JWKS_URL` falls
    # back to the platform's `CELINE_OIDC_JWKS_URI` (set by the infra chart) so a
    # deployment that configures the SDK's OIDC settings also configures this verifier
    # rather than silently trusting the issuer the token names for itself.
    oauth2_jwks_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("OAUTH2_JWKS_URL", "CELINE_OIDC_JWKS_URI"),
    )
    oauth2_issuer: str | None = Field(default=None, alias="OAUTH2_ISSUER")
    # Signature algorithms accepted at verification. Pinned here rather than read from
    # the token header, so a caller cannot choose the algorithm their token is checked
    # against.
    oauth2_algorithms: list[str] = Field(
        default_factory=lambda: ["RS256"], alias="OAUTH2_ALGORITHMS"
    )
    oauth2_audience: str | None = Field(default="oauth2_proxy", alias="OAUTH2_AUDIENCE")
    oauth2_jwt_cookie_name: str | None = Field(
        default=None, alias="OAUTH2_JWT_COOKIE_NAME"
    )

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
    flexibility_api_url: str | None = Field(
        default="http://172.17.0.1:8017",
        alias="FLEXIBILITY_API_URL",
    )

    max_tool_rounds: int = Field(default=6, alias="MAX_TOOL_ROUNDS")
    max_tool_result_chars: int = Field(default=8000, alias="MAX_TOOL_RESULT_CHARS")
    chat_history_limit: int = Field(default=20, alias="CHAT_HISTORY_LIMIT")
    chat_word_limit: int = Field(default=25000, alias="CHAT_WORD_LIMIT")
    chat_hot_messages: int = Field(default=6, alias="CHAT_HOT_MESSAGES")


settings = Settings()
