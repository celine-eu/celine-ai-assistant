# Configuration

All settings are defined in `src/celine/assistant/settings.py` using `pydantic-settings`. Values are read from environment variables.

## Required Settings

| Variable | Type | Description |
|---|---|---|
| `OPENAI_API_KEY` | `str` | OpenAI API key |
| `DATABASE_URL` | `str` | PostgreSQL async connection string (`postgresql+asyncpg://...`) |
| `JWKS_URL` | `str` | JWKS endpoint for JWT signature verification |
| `QDRANT_URL` | `str` | Qdrant base URL |

## Optional Settings

| Variable | Type | Default | Description |
|---|---|---|---|
| `OPENAI_MODEL` | `str` | `gpt-4o` | Chat completion model |
| `EMBED_MODEL` | `str` | `text-embedding-3-small` | Embedding model for indexing and retrieval |
| `QDRANT_COLLECTION` | `str` | `celine_docs` | Qdrant collection name |
| `TOP_K` | `int` | `5` | Number of retrieved context chunks per query |
| `MAX_HISTORY_MESSAGES` | `int` | `20` | Maximum messages loaded from history per request |
| `S3_ENDPOINT_URL` | `str` | none | S3-compatible storage endpoint (if used) |
| `S3_BUCKET` | `str` | `assistant-uploads` | Bucket for raw file uploads |
| `LOG_LEVEL` | `str` | `INFO` | Python log level |
| `TRAINING_MATERIALS_PATH` | `str` | `/workspace/repositories/celine-training-materials` | Local checkout path used for Markdown ingestion |
| `TRAINING_MATERIALS_REPO_URL` | `str` | empty | Git URL to clone/pull `celine-training-materials` from inside the container |
| `TRAINING_MATERIALS_REF` | `str` | `origin/main` | Git ref checked out before ingestion |
| `TRAINING_MATERIALS_SYNC_ON_START` | `bool` | `true` | If true, clone/fetch/checkout the training repo on startup before ingestion |

## Docker Compose Example

```yaml
environment:
  OPENAI_API_KEY: sk-...
  DATABASE_URL: postgresql+asyncpg://postgres:postgres@db:5432/assistant
  JWKS_URL: http://keycloak:8080/realms/celine/protocol/openid-connect/certs
  QDRANT_URL: http://qdrant:6333
  TRAINING_MATERIALS_PATH: /app/training-materials
  TRAINING_MATERIALS_REPO_URL: https://<token>@github.com/celine-eu/celine-training-materials.git
  TRAINING_MATERIALS_REF: origin/main
```

## Notes

- `JWKS_URL` must be reachable at startup. The JWKS is fetched lazily on first request and cached.
- `DATABASE_URL` must use the `asyncpg` driver for async SQLAlchemy compatibility.
- Storage for uploads defaults to local disk if `S3_ENDPOINT_URL` is not set.
- In Kubernetes, use an authenticated HTTPS Git URL or another credentialed Git transport for `TRAINING_MATERIALS_REPO_URL`.
