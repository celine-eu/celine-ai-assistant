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
| `QDRANT_API_KEY` | `str?` | — | Qdrant API key. Required outside `CELINE_ENV=dev` |
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
| `OAUTH2_TRUST_HEADERS` | `bool` | `false` | Trust unverified `x-auth-request-*` headers for requests carrying no token. Opt-in; safe only behind a trusted proxy on an isolated network. Refused at startup outside `CELINE_ENV=dev` |
| `OAUTH2_JWKS_URL` | `str?` | — | JWKS endpoint for JWT verification. Falls back to `CELINE_OIDC_JWKS_URI`. If unset, `OAUTH2_ISSUER` must be set |
| `OAUTH2_ISSUER` | `str?` | — | Expected token issuer; the JWKS is discovered from it. A token whose `iss` differs is refused. Required outside `CELINE_ENV=dev`: with `OAUTH2_JWKS_URL` alone `iss` is not checked |
| `OAUTH2_ALGORITHMS` | `list[str]` | `["RS256"]` | Accepted signature algorithms. Pinned, not read from the token header |
| `OAUTH2_AUDIENCE` | `str?` | `oauth2_proxy` | Expected JWT audience |
| `OAUTH2_JWT_COOKIE_NAME` | `str?` | — | Optional JWT cookie name |
| `REC_ORGANIZATION_TYPE` | `str` | `rec` | Organization type marking a REC in the token's `organization` claim; its alias is the caller's community |
| `REC_MANAGER_GROUPS` | `list[str]` | `["managers", "admins"]` | Groups inside a REC's own organization that may share documents with it and sync its sources |

## Knowledge bases

| Variable | Type | Default | Description |
|---|---|---|---|
| `QDRANT_COLLECTION` | `str` | `celine_docs` | Prefix of every knowledge-base alias, `<prefix>__<community_id>__<fingerprint>`. Before 2026-10-02 the one collection; `kb migrate-legacy` moves it |
| `KB_SOURCES_DIR` | `str` | `./data/kb-sources` | Where git sources are cloned, one directory per source |
| `KB_SYNC_ON_START` | `bool` | `false` | Sync every registered source when the service starts |
| `KB_GIT_TOKEN` | `str` | — | Token for cloning private git sources over HTTPS (GitHub: fine-grained, read-only Contents). Sent as a header to `KB_GIT_TOKEN_HOST` only; never stored |
| `KB_GIT_TOKEN_HOST` | `str` | `github.com` | The host the token is sent to |

Sources themselves are not configuration: they are registered per community with
`celine-assistant kb source add` and stored in the database.

**No longer read** — reported at startup when set: `TRAINING_MATERIALS_PATH`,
`TRAINING_MATERIALS_REPO_URL`, `TRAINING_MATERIALS_REF`,
`TRAINING_MATERIALS_SYNC_ON_START`, `MANIFEST_PATH`, `INGEST_ENABLE`,
`INGEST_FORCE_RELOAD_ON_START`, `DOCS_POLL_INTERVAL_SECONDS`.

## Uploads and Ingestion

| Variable | Type | Default | Description |
|---|---|---|---|
| `UPLOADS_URI` | `str` | `file://./data/uploads` | Upload storage URI |
| `MAX_UPLOAD_MB` | `int` | `25` | Maximum upload file size in MB |

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
| `CELINE_ENV` | `str` | — | Deployment posture. Only `dev` relaxes: wildcard CORS, header trust, SQL echo, and the values below accepted with a warning. Unset, `prod`, `staging` or anything else is hardened and startup refuses them. Read from the process environment; `task run` exports `dev` |
| `ENVIRONMENT` | `str` | — | Read when `CELINE_ENV` is unset |
| `APP_ENV` | `str` | — | Legacy name, read after `CELINE_ENV` and `ENVIRONMENT` (also from `.env`). Its old `prod` default no longer decides anything |
| `LOG_LEVEL` | `str` | `INFO` | Python log level |

## Notes

- `DATABASE_URL` must use the `asyncpg` driver for async SQLAlchemy compatibility. Outside `CELINE_ENV=dev` a development database password is refused at startup.
- Outside `CELINE_ENV=dev`, startup refuses `OAUTH2_TRUST_HEADERS=true`, an unset `OAUTH2_ISSUER` or `QDRANT_API_KEY`, and a development database password, all named in one message (REQ-0045). Wildcard CORS is served in dev only (REQ-0046).
- A presented token is always verified against a configured trust anchor (`OAUTH2_JWKS_URL` or `OAUTH2_ISSUER`); it is never trusted on the strength of the issuer it names for itself, and the algorithm is taken from `OAUTH2_ALGORITHMS`, not the token header. A token that does not verify is refused, never downgraded to header trust.
- `OAUTH2_TRUST_HEADERS` governs only requests that carry *no* token: with it on, `x-auth-request-user`/`-email`/`-groups` are accepted as identity. This is safe only when the network guarantees those headers can be set by the proxy alone (see ADR-0003).
- Upload storage defaults to local disk. The `UPLOADS_URI` supports `file://` and `s3://` schemes.
- Skills (Digital Twin, Weather, Flexibility, REC Registry) are registered per-request only when the matching service URL is configured and a user token is available.
