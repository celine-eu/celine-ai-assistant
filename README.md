# CELINE AI Assistant

FastAPI API backend for the CELINE AI assistant. Implements a RAG (Retrieval-Augmented Generation) pipeline using LlamaIndex, Qdrant, and OpenAI. Provides streaming chat, conversation history, file-based RAG ingestion, and JWT authentication.

The chat UI is part of [celine-frontend](https://github.com/celine-eu/celine-frontend) (`apps/assistant` and `@celine-eu/assistant-ui`).

## Features

- Streaming chat via Server-Sent Events (SSE)
- Conversation history persisted in PostgreSQL
- File upload with automatic RAG ingestion into Qdrant
- Automatic sync of `celine-training-materials` from a Git repository
- JWT authentication (JWKS-based verification)
- Vision support for image attachments
- Admin endpoints for re-indexing and reloading
- Internal knowledge ingestion from Markdown files in the documentation repository

## Quick Start

```bash
# Start all services (Qdrant, PostgreSQL, API)
docker compose up -d

# Send a chat message
curl -X POST http://localhost:8000/chat \
  -H "Authorization: Bearer <jwt>" \
  -H "Content-Type: application/json" \
  -d '{"message": "What is a renewable energy community?"}' \
  --no-buffer
```

## Configuration

| Variable | Description | Default |
|---|---|---|
| `OPENAI_API_KEY` | OpenAI API key | required |
| `QDRANT_URL` | Qdrant vector DB URL | `http://localhost:6333` |
| `DATABASE_URL` | PostgreSQL async URL | required |
| `JWKS_URL` | JWKS endpoint for JWT verification | required |
| `OPENAI_MODEL` | Chat model | `gpt-4o` |
| `EMBED_MODEL` | Embedding model | `text-embedding-3-small` |
| `TRAINING_MATERIALS_PATH` | Local checkout path for training materials | `/app/training-materials` in container deployments |
| `TRAINING_MATERIALS_REPO_URL` | Git URL used by the API container to clone/pull training materials | empty |
| `TRAINING_MATERIALS_REF` | Ref checked out before ingest | `origin/main` |

## Training Materials Sync

The API can manage the `celine-training-materials` repository directly inside the container.

- If `TRAINING_MATERIALS_REPO_URL` is set, the container clones the repo into `TRAINING_MATERIALS_PATH` if missing.
- On startup, it fetches `origin`, checks out `TRAINING_MATERIALS_REF`, and ingests Markdown files.
- Admins can force a new sync through `POST /admin/training-materials/sync`.

For Kubernetes, prefer an authenticated HTTPS URL, for example via a token-backed secret injected into `TRAINING_MATERIALS_REPO_URL`.

The assistant preloads internal knowledge from the local checkout of `celine-training-materials`, mounted in the container via the parent workspace at `/workspace/repositories/celine-training-materials`. It indexes all Markdown files found there. This is intended for docs that should influence answers without being shown as visible sources in the chat UI.

## Documentation

| Document | Description |
|---|---|
| [Architecture](https://celine-eu.github.io/projects/celine-ai-assistant/docs/architecture) | RAG pipeline, component overview, service dependencies |
| [Configuration](https://celine-eu.github.io/projects/celine-ai-assistant/docs/configuration) | All environment variables with types and defaults |
| [API Reference](https://celine-eu.github.io/projects/celine-ai-assistant/docs/api-reference) | All endpoints: chat, upload, attachments, conversations, admin |
| [Development](https://celine-eu.github.io/projects/celine-ai-assistant/docs/development) | Local setup, migrations, running tests |

## License

Apache 2.0 — Copyright © 2025 Spindox Labs
