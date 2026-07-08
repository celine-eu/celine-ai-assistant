# CELINE AI Assistant

FastAPI backend for the CELINE AI assistant. Implements a RAG (Retrieval-Augmented Generation) pipeline using LlamaIndex, Qdrant, and OpenAI. Provides streaming chat, conversation history, file uploads with vision support, and JWT authentication.

The chat UI is part of [celine-frontend](https://github.com/celine-eu/celine-frontend) (`apps/assistant`).

## Features

- **Agentic chat** with tool-calling loop — the LLM autonomously invokes skills to fetch live data
- **Skill system** — modular skills for energy data (Digital Twin), weather/forecasts, flexibility/gamification, REC registry, and document search
- Streaming chat via Server-Sent Events (SSE) with tool progress events
- Conversation history persisted in PostgreSQL
- File upload with automatic RAG ingestion into Qdrant
- Vision support for image attachments (captioning via OpenAI vision model)
- Automatic sync of `celine-training-materials` from a Git repository
- JWT authentication (trusted headers from oauth2_proxy or JWKS verification)
- Admin endpoints for system uploads and training materials sync

## Quick Start

```bash
uv sync
uv run alembic upgrade head
task run
# Listens on http://localhost:8012
```

## Configuration

| Variable | Default | Description |
|---|---|---|
| `OPENAI_API_KEY` | — | OpenAI API key (required) |
| `OPENAI_CHAT_MODEL` | `gpt-5.4-mini` | Chat completion model |
| `OPENAI_EMBED_MODEL` | `text-embedding-3-small` | Embedding model |
| `OPENAI_VISION_MODEL` | `gpt-4o-mini` | Vision model for image captioning |
| `QDRANT_URL` | `http://host.docker.internal:6333` | Qdrant vector DB URL |
| `QDRANT_API_KEY` | — | Optional Qdrant API key |
| `QDRANT_COLLECTION` | `celine_docs` | Qdrant collection name |
| `DATABASE_URL` | `postgresql+asyncpg://...host.docker.internal:15432/ai_assistant` | PostgreSQL async URL |
| `OAUTH2_TRUST_HEADERS` | `true` | Trust headers from oauth2_proxy |
| `OAUTH2_JWKS_URL` | — | JWKS endpoint (auto-discovered if not set) |
| `OAUTH2_ISSUER` | — | OAuth2 issuer URL |
| `OAUTH2_AUDIENCE` | `oauth2_proxy` | Expected JWT audience |
| `ADMIN_GROUP` | `admins` | Group name for admin access |
| `DIGITAL_TWIN_API_URL` | `http://172.17.0.1:8002` | Digital Twin API for energy/weather/forecast skills |
| `DATASETS_API_URL` | `http://172.17.0.1:8001` | Dataset API (skill currently disabled) |
| `REC_REGISTRY_API_URL` | `http://172.17.0.1:8004` | REC Registry API for membership/assets/delivery points |
| `FLEXIBILITY_API_URL` | `http://172.17.0.1:8017` | Flexibility API for load-shift suggestions and gamification |
| `MAX_TOOL_ROUNDS` | `6` | Max agentic tool-calling rounds per chat request |
| `CHAT_HISTORY_LIMIT` | `20` | Max prior messages included in the prompt |
| `TRAINING_MATERIALS_PATH` | `/workspace/repositories/celine-training-materials` | Local path for training materials |
| `TRAINING_MATERIALS_REPO_URL` | — | Git URL for auto-cloning training materials |
| `TRAINING_MATERIALS_REF` | `origin/main` | Git ref for training materials |
| `TRAINING_MATERIALS_SYNC_ON_START` | `true` | Auto-sync training materials on startup |
| `UPLOADS_URI` | `file://./data/uploads` | Upload storage URI |
| `MAX_UPLOAD_MB` | `25` | Max upload size in MB |
| `INGEST_ENABLE` | `true` | Enable RAG ingestion |

## API Overview

| Group | Endpoints |
|---|---|
| **chat** | `POST /chat` (SSE streaming with agentic tool calls) |
| **ping** | `GET /ping` (authenticated liveness check) |
| **suggestions** | `GET /suggestions` (localized prompt suggestions and tool labels) |
| **conversations** | `GET /conversations`, `GET /conversations/{id}/messages`, `DELETE /conversations/{id}` |
| **attachments** | `GET /attachments`, `GET /attachments/{id}/raw`, `DELETE /attachments/{id}` |
| **uploads** | `POST /upload` (user), `POST /admin/uploads` (system) |
| **admin** | `POST /admin/training-materials/sync` |
| **user** | `GET /user` |
| **ops** | `GET /health` |

## Skills

The assistant uses a modular skill system. Each skill exposes OpenAI function-calling tools that the LLM invokes autonomously during conversation. Skills are registered per-request based on available API endpoints and user authentication.

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
