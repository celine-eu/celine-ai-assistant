# Configuration

All settings are defined in `src/celine/assistant/settings.py` using `pydantic-settings`. Values are read from environment variables or `.env` file.

## Models

Every model call goes to an OpenAI-compatible endpoint: chat, conversation summaries,
image captions and embeddings. vLLM, Ollama and the llama.cpp server all expose one.
What crosses it is the member's messages and attachments and the data the tools fetch
with the member's token. The endpoint therefore has **no default**: startup refuses
without `LLM_BASE_URL`. To use OpenAI itself, set `https://api.openai.com/v1`.

| Variable | Type | Default | Description |
|---|---|---|---|
| `LLM_BASE_URL` | `str` | — | OpenAI-compatible endpoint (required) |
| `LLM_API_KEY` | `str` | — | Key for that endpoint, if it needs one |
| `LLM_CHAT_MODEL` | `str` | — | Chat model; must support tool calling (required) |
| `LLM_VISION_MODEL` | `str` | the chat model | Vision model for image captioning |
| `LLM_EMBED_BASE_URL` | `str` | `LLM_BASE_URL` | Separate endpoint for embeddings |
| `LLM_EMBED_API_KEY` | `str` | `LLM_API_KEY` | Key for the embeddings endpoint |
| `LLM_EMBED_MODEL` | `str` | — | Embedding model for indexing and retrieval (required) |
| `LLM_EMBED_DIMENSIONS` | `int?` | asked of the model | Vector size the collection is created with |

The `OPENAI_*` variables used before 2026-10-01 are no longer read. If one is set,
startup refuses and names its replacement.

**Changing the embedding model needs a new collection.** A collection holds vectors of
one size. If `QDRANT_COLLECTION` already exists with a different size, startup refuses.
To switch:

1. Set a new collection name.
2. Re-ingest the corpus (`INGEST_FORCE_RELOAD_ON_START=true`).

Uploaded attachments are not re-indexed. No command does it yet. Their files and text
stay in storage and PostgreSQL, but the assistant cannot retrieve them from the new
collection until they are uploaded again.

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
| `OAUTH2_TRUST_HEADERS` | `bool` | `false` | Trust unverified `x-auth-request-*` headers for requests carrying no token. Opt-in; safe only behind a trusted proxy on an isolated network |
| `OAUTH2_JWKS_URL` | `str?` | — | JWKS endpoint for JWT verification. Falls back to `CELINE_OIDC_JWKS_URI`. If unset, `OAUTH2_ISSUER` must be set |
| `OAUTH2_ISSUER` | `str?` | — | Expected token issuer; the JWKS is discovered from it. A token whose `iss` differs is refused |
| `OAUTH2_ALGORITHMS` | `list[str]` | `["RS256"]` | Accepted signature algorithms. Pinned, not read from the token header |
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

## Service URLs

| Variable | Type | Default | Description |
|---|---|---|---|
| `DIGITAL_TWIN_API_URL` | `str?` | `http://172.17.0.1:8002` | Digital Twin API for energy, weather, and forecast skills |
| `DATASETS_API_URL` | `str?` | `http://172.17.0.1:8001` | Dataset API (skill currently disabled — requires service tokens) |
| `REC_REGISTRY_API_URL` | `str?` | `http://172.17.0.1:8004` | REC Registry API for membership, assets, and delivery points |
| `FLEXIBILITY_API_URL` | `str?` | `http://172.17.0.1:8017` | Flexibility API for load-shift suggestions and gamification |

## Chat Tuning

| Variable | Type | Default | Description |
|---|---|---|---|
| `MAX_TOOL_ROUNDS` | `int` | `6` | Max agentic tool-calling rounds per chat request |
| `MAX_TOOL_RESULT_CHARS` | `int` | `8000` | Max characters per tool result before truncation |
| `CHAT_HISTORY_LIMIT` | `int` | `20` | Max prior messages included in the prompt |
| `CHAT_WORD_LIMIT` | `int` | `25000` | Word budget for the conversation context window |
| `CHAT_HOT_MESSAGES` | `int` | `6` | Number of recent messages sent without summarization |

## General

| Variable | Type | Default | Description |
|---|---|---|---|
| `APP_ENV` | `str` | `prod` | Application environment |
| `LOG_LEVEL` | `str` | `INFO` | Python log level |

## Notes

- `DATABASE_URL` must use the `asyncpg` driver for async SQLAlchemy compatibility.
- A presented token is always verified against a configured trust anchor (`OAUTH2_JWKS_URL` or `OAUTH2_ISSUER`); it is never trusted on the strength of the issuer it names for itself, and the algorithm is taken from `OAUTH2_ALGORITHMS`, not the token header. A token that does not verify is refused, never downgraded to header trust.
- `OAUTH2_TRUST_HEADERS` governs only requests that carry *no* token: with it on, `x-auth-request-user`/`-email`/`-groups` are accepted as identity. This is safe only when the network guarantees those headers can be set by the proxy alone (see ADR-0003).
- Upload storage defaults to local disk. The `UPLOADS_URI` supports `file://` and `s3://` schemes.
- Skills (Digital Twin, Weather, Flexibility, REC Registry) are registered per-request only when the matching service URL is configured and a user token is available.
