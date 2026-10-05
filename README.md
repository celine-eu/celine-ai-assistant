# CELINE AI Assistant

FastAPI backend for the CELINE AI assistant. Implements a RAG (Retrieval-Augmented Generation) pipeline using LlamaIndex, Qdrant, and any OpenAI-compatible model endpoint. Provides streaming chat, conversation history, file uploads with vision support, and JWT authentication.

The chat UI is part of [celine-frontend](https://github.com/celine-eu/celine-frontend) (`apps/assistant`).

## Features

- **Agentic chat** with tool-calling loop — the LLM autonomously invokes skills to fetch live data
- **Skill system** — modular skills for energy data (Digital Twin), weather/forecasts, flexibility/gamification, REC registry, and document search
- Streaming chat via Server-Sent Events (SSE) with tool progress events
- Conversation history persisted in PostgreSQL
- **One knowledge base per REC** — each community's documents in a Qdrant collection of its own, resolved from the REC organization in the caller's token
- File upload with automatic RAG ingestion into the caller's community
- Vision support for image attachments (captioning via the vision model)
- Knowledge sources (git repositories or directories) registered per community
- `celine-assistant kb` CLI to sync sources, rebuild knowledge bases and switch embedding models
- JWT authentication (trusted headers from oauth2_proxy or JWKS verification)
- Admin endpoints for REC managers: shared uploads and source sync

## Quick Start

```bash
uv sync
uv run alembic upgrade head
task run
# Listens on http://localhost:8012
```

`task run` exports `CELINE_ENV=dev`, the only value that relaxes anything: wildcard
CORS, `OAUTH2_TRUST_HEADERS=true`, an unset `OAUTH2_ISSUER` or `QDRANT_API_KEY`, and the
development database password are accepted in dev with one warning, and refused at
startup anywhere else. **Unset is hardened.** The signal is `CELINE_ENV`, then
`ENVIRONMENT`, then the legacy `APP_ENV` (still accepted as a fallback name);
`CELINE_ENV=staging task run` is the prod-like mode of the same entry point.

The check comes from `celine.sdk.posture`, first released in celine-sdk 2.0.0.

## Configuration

| Variable | Default | Description |
|---|---|---|
| `LLM_BASE_URL` | — | OpenAI-compatible endpoint for every model call (required, no default) |
| `LLM_API_KEY` | — | Key for that endpoint, if it needs one |
| `LLM_CHAT_MODEL` | — | Chat model, with tool calling (required) |
| `LLM_VISION_MODEL` | the chat model | Vision model for image captioning |
| `LLM_EMBED_BASE_URL` / `LLM_EMBED_API_KEY` | the chat endpoint | Separate endpoint for embeddings |
| `LLM_EMBED_MODEL` | — | Embedding model (required) |
| `LLM_EMBED_DIMENSIONS` | asked of the model | Vector size of the collection |
| `QDRANT_URL` | `http://host.docker.internal:6333` | Qdrant vector DB URL |
| `QDRANT_API_KEY` | — | Qdrant API key; required outside `CELINE_ENV=dev` |
| `QDRANT_COLLECTION` | `celine_docs` | Prefix of every community's knowledge-base alias |
| `KB_SOURCES_DIR` | `./data/kb-sources` | Where git sources are cloned |
| `KB_SYNC_ON_START` | `false` | Sync every registered source when the service starts |
| `KB_GIT_TOKEN` | — | Token for private git sources (sent only to `KB_GIT_TOKEN_HOST`, default `github.com`) |
| `REC_ORGANIZATION_TYPE` | `rec` | Organization type that marks a REC in the token's `organization` claim |
| `REC_MANAGER_GROUPS` | `["managers","admins"]` | Groups inside a REC's organization that manage its knowledge |
| `DATABASE_URL` | `postgresql+asyncpg://...host.docker.internal:15432/ai_assistant` | PostgreSQL async URL |
| `OAUTH2_TRUST_HEADERS` | `false` | Trust unverified proxy headers when no token is present (opt-in, `CELINE_ENV=dev` only) |
| `OAUTH2_JWKS_URL` | — | JWKS endpoint (falls back to `CELINE_OIDC_JWKS_URI`); required unless `OAUTH2_ISSUER` is set |
| `OAUTH2_ISSUER` | — | Expected issuer; JWKS discovered from it, and a mismatching token `iss` is refused. Required outside `CELINE_ENV=dev` |
| `OAUTH2_ALGORITHMS` | `["RS256"]` | Accepted signature algorithms (pinned, not from the token header) |
| `OAUTH2_AUDIENCE` | `oauth2_proxy` | Expected JWT audience |
| `DIGITAL_TWIN_API_URL` | `http://172.17.0.1:8002` | Digital Twin API for energy/weather/forecast skills |
| `DATASETS_API_URL` | `http://172.17.0.1:8001` | Dataset API (skill currently disabled) |
| `REC_REGISTRY_API_URL` | `http://172.17.0.1:8004` | REC Registry API for membership/assets/delivery points |
| `FLEXIBILITY_API_URL` | `http://172.17.0.1:8017` | Flexibility API for load-shift suggestions and gamification |
| `MAX_TOOL_ROUNDS` | `6` | Max agentic tool-calling rounds per chat request |
| `CHAT_HISTORY_LIMIT` | `20` | Max prior messages included in the prompt |
| `UPLOADS_URI` | `file://./data/uploads` | Upload storage URI |
| `MAX_UPLOAD_MB` | `25` | Max upload size in MB |

`TRAINING_MATERIALS_*`, `MANIFEST_PATH`, `INGEST_ENABLE`, `INGEST_FORCE_RELOAD_ON_START`
and `DOCS_POLL_INTERVAL_SECONDS` are no longer read; a leftover is logged at startup.

## API Overview

| Group | Endpoints |
|---|---|
| **chat** | `POST /chat` (SSE streaming with agentic tool calls) |
| **ping** | `GET /ping` (authenticated liveness check) |
| **suggestions** | `GET /suggestions` (localized prompt suggestions and tool labels) |
| **conversations** | `GET /conversations`, `GET /conversations/{id}/messages`, `DELETE /conversations/{id}` |
| **attachments** | `GET /attachments`, `GET /attachments/{id}/raw`, `DELETE /attachments/{id}` |
| **uploads** | `POST /upload` (user), `POST /admin/uploads` (shared with a community) |
| **admin** | `POST /admin/kb/sync` |
| **user** | `GET /user` |
| **ops** | `GET /health` |

## Knowledge bases

Each REC has its own knowledge base: the sources registered for it, the documents its
managers shared, and its members' own uploads. A caller's community is the one
organization of type `rec` in their token; a token naming several is refused. See
[ADR-0008](docs/decisions/ADR-0008-one-knowledge-base-per-community.md).

They are operated with `celine-assistant kb`, run in the service image (it needs the
service's `DATABASE_URL`, `QDRANT_*` and `LLM_EMBED_*`). Every command prints JSON.

```bash
# register sources: a git repository (optionally a ref and a subdirectory) or a directory
celine-assistant kb source add --community example-rec --git https://git.example/handbook.git --ref main --path docs
celine-assistant kb source add --community example-rec --dir /data/example-rec-handbook
celine-assistant kb source list
celine-assistant kb sync [--community example-rec] [--full]

# rebuild from the sources and the stored attachment text, then switch atomically
celine-assistant kb reindex --community example-rec [--re-extract]
celine-assistant kb reindex --all
celine-assistant kb status
celine-assistant kb prune [--keep 1] [--dry-run]
```

**Switching the embedding model.** Build the new model's knowledge bases beside the
current ones, deploy with the new model, then drop the old generations:

```bash
celine-assistant kb reindex --all --embed-model <new-model> --embed-dimensions <size>
# deploy with LLM_EMBED_MODEL=<new-model>
celine-assistant kb prune
```

The service refuses to start if a community has knowledge bases only for a model other
than `LLM_EMBED_MODEL`.

**Upgrading from the single collection.** Once, after `alembic upgrade head`: assign
every existing upload to one community, register the old training-materials repository
as its source, and rebuild it. The community is always named; there is no default.

```bash
celine-assistant kb migrate-legacy --community <community> --git <training-materials repo> --dry-run
celine-assistant kb migrate-legacy --community <community> --git <training-materials repo>
celine-assistant kb prune --legacy   # once satisfied: deletes the old collection
```

## Skills

The assistant uses a modular skill system. Each skill exposes OpenAI-style function-calling tools that the LLM invokes autonomously during conversation. Skills are registered per-request based on available API endpoints and user authentication.

| Skill | Tools | Data source |
|---|---|---|
| **Digital Twin** | `query_participant_metrics`, `query_community_metrics`, `query_participant_profile`, `query_participant_assets` | Digital Twin API |
| **Weather** | `get_weather_current`, `get_weather_forecast`, `get_weather_alerts`, `get_energy_forecast` | Digital Twin API (weather fetchers) |
| **Flexibility** | `get_flexibility_suggestions`, `get_gamification_status`, `get_commitment_history` | Flexibility API + Digital Twin API |
| **REC Registry** | `get_my_rec_profile`, `get_my_community_details`, `get_my_assets`, `get_my_asset_detail`, `get_my_delivery_points` | REC Registry API |
| **Documents** | `search_documents`, `get_attachment_info` | Qdrant vector store |

## Documentation

| Document | Description |
|---|---|
| [Architecture](docs/architecture.md) | RAG pipeline, component overview, service dependencies |
| [Configuration](docs/configuration.md) | All environment variables with types and defaults |
| [API Reference](docs/api-reference.md) | All endpoints: chat, upload, attachments, conversations, admin |
| [Development](docs/development.md) | Local setup, migrations, taskfile commands |

## License

Apache 2.0 — Copyright © 2025 Spindox Labs
