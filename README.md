# CELINE AI Assistant

FastAPI backend for the CELINE AI assistant. Implements a RAG (Retrieval-Augmented Generation) pipeline using LlamaIndex, Qdrant, and OpenAI. Provides streaming chat, conversation history, file uploads with vision support, and JWT authentication.

The chat UI is part of [celine-frontend](https://github.com/celine-eu/celine-frontend) (`apps/assistant`).

## Features

- Streaming chat via Server-Sent Events (SSE)
- Conversation history persisted in PostgreSQL
- File upload with automatic RAG ingestion into Qdrant
- Vision support for image attachments (captioning via OpenAI vision model)
- Dashboard context enrichment from Digital Twin API
- Automatic sync of `celine-training-materials` from a Git repository
- Page-aware context and attachment scoping
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
| `OPENAI_CHAT_MODEL` | `gpt-4o-mini` | Chat completion model |
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
| `DIGITAL_TWIN_API_URL` | — | Digital Twin API for dashboard context |
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
| **chat** | `POST /chat` (SSE streaming) |
| **conversations** | `GET /conversations`, `GET /conversations/{id}/messages`, `DELETE /conversations/{id}` |
| **attachments** | `GET /attachments`, `GET /attachments/{id}/raw`, `DELETE /attachments/{id}` |
| **uploads** | `POST /upload` (user), `POST /admin/uploads` (system) |
| **admin** | `POST /admin/training-materials/sync` |
| **user** | `GET /user` |
| **ops** | `GET /health` |

## Documentation

| Document | Description |
|---|---|
| [Architecture](docs/architecture.md) | RAG pipeline, component overview, service dependencies |
| [Configuration](docs/configuration.md) | All environment variables with types and defaults |
| [API Reference](docs/api-reference.md) | All endpoints: chat, upload, attachments, conversations, admin |
| [Development](docs/development.md) | Local setup, migrations, taskfile commands |

## License

Apache 2.0 — Copyright © 2025 Spindox Labs
