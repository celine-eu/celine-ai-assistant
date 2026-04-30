# Configuration

All settings are defined in `src/celine/assistant/settings.py` using `pydantic-settings`. Values are read from environment variables or `.env` file.

## OpenAI Settings

| Variable | Type | Default | Description |
|---|---|---|---|
| `OPENAI_API_KEY` | `str` | — | OpenAI API key (required) |
| `OPENAI_CHAT_MODEL` | `str` | `gpt-4o-mini` | Chat completion model |
| `OPENAI_EMBED_MODEL` | `str` | `text-embedding-3-small` | Embedding model for indexing and retrieval |
| `OPENAI_VISION_MODEL` | `str` | `gpt-4o-mini` | Vision model for image captioning |

## Vector Store

| Variable | Type | Default | Description |
|---|---|---|---|
| `QDRANT_URL` | `str` | `http://host.docker.internal:6333` | Qdrant base URL |
| `QDRANT_API_KEY` | `str?` | — | Optional Qdrant API key |
| `QDRANT_COLLECTION` | `str` | `celine_docs` | Qdrant collection name |

## Database

| Variable | Type | Default | Description |
|---|---|---|---|
| `DATABASE_URL` | `str` | `postgresql+asyncpg://...host.docker.internal:15432/ai_assistant` | PostgreSQL async connection string |
| `DB_POOL_SIZE` | `int` | `10` | Connection pool size |
| `DB_MAX_OVERFLOW` | `int` | `20` | Max overflow connections |
| `DB_POOL_TIMEOUT` | `int` | `30` | Pool timeout in seconds |
| `DB_POOL_RECYCLE` | `int` | `1800` | Connection recycle time in seconds |

## Authentication

| Variable | Type | Default | Description |
|---|---|---|---|
| `OAUTH2_TRUST_HEADERS` | `bool` | `true` | Trust JWT from proxy headers (oauth2_proxy) |
| `OAUTH2_JWKS_URL` | `str?` | — | JWKS endpoint for JWT verification (auto-discovered if not set) |
| `OAUTH2_ISSUER` | `str?` | — | OAuth2 issuer URL |
| `OAUTH2_AUDIENCE` | `str?` | `oauth2_proxy` | Expected JWT audience |
| `OAUTH2_JWT_COOKIE_NAME` | `str?` | — | Optional JWT cookie name |
| `ADMIN_GROUP` | `str` | `admins` | Group name for admin access |

## Training Materials

| Variable | Type | Default | Description |
|---|---|---|---|
| `TRAINING_MATERIALS_PATH` | `str` | `/workspace/repositories/celine-training-materials` | Local checkout path for training materials |
| `TRAINING_MATERIALS_REPO_URL` | `str` | — | Git URL to clone/pull training materials |
| `TRAINING_MATERIALS_REF` | `str` | `origin/main` | Git ref checked out before ingestion |
| `TRAINING_MATERIALS_SYNC_ON_START` | `bool` | `true` | Auto-sync training materials on startup |

## Uploads and Ingestion

| Variable | Type | Default | Description |
|---|---|---|---|
| `UPLOADS_URI` | `str` | `file://./data/uploads` | Upload storage URI |
| `MAX_UPLOAD_MB` | `int` | `25` | Maximum upload file size in MB |
| `INGEST_ENABLE` | `bool` | `true` | Enable RAG ingestion |
| `INGEST_FORCE_RELOAD_ON_START` | `bool` | `false` | Force re-ingest all documents on startup |
| `MANIFEST_PATH` | `str` | `/app/data/manifest.json` | Manifest file for tracking ingested documents |
| `DOCS_POLL_INTERVAL_SECONDS` | `int` | `60` | Polling interval for document changes |

## General

| Variable | Type | Default | Description |
|---|---|---|---|
| `APP_ENV` | `str` | `prod` | Application environment |
| `LOG_LEVEL` | `str` | `INFO` | Python log level |
| `DIGITAL_TWIN_API_URL` | `str?` | — | Digital Twin API URL for dashboard context enrichment |

## Notes

- `DATABASE_URL` must use the `asyncpg` driver for async SQLAlchemy compatibility.
- When `OAUTH2_TRUST_HEADERS` is `true`, the JWT from `x-auth-request-access-token` header is trusted without JWKS verification (used behind oauth2_proxy).
- Upload storage defaults to local disk. The `UPLOADS_URI` supports `file://` and `s3://` schemes.
