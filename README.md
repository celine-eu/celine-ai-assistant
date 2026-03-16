# CELINE AI Assistant

FastAPI API backend for the CELINE AI assistant. Implements a RAG (Retrieval-Augmented Generation) pipeline using LlamaIndex, Qdrant, and OpenAI. Provides streaming chat, conversation history, file-based RAG ingestion, and JWT authentication.

The chat UI is part of [celine-frontend](https://github.com/celine-eu/celine-frontend) (`apps/assistant` and `@celine-eu/assistant-ui`).

## Features

- Streaming chat via Server-Sent Events (SSE)
- Conversation history persisted in PostgreSQL
- File upload with automatic RAG ingestion into Qdrant
- JWT authentication (JWKS-based verification)
- Vision support for image attachments
- Admin endpoints for re-indexing and reloading

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

## Documentation

| Document | Description |
|---|---|
| [Architecture](https://celine-eu.github.io/projects/celine-ai-assistant/docs/architecture.md) | RAG pipeline, component overview, service dependencies |
| [Configuration](https://celine-eu.github.io/projects/celine-ai-assistant/docs/configuration.md) | All environment variables with types and defaults |
| [API Reference](https://celine-eu.github.io/projects/celine-ai-assistant/docs/api-reference.md) | All endpoints: chat, upload, attachments, conversations, admin |
| [Development](https://celine-eu.github.io/projects/celine-ai-assistant/docs/development.md) | Local setup, migrations, running tests |

## License

Apache 2.0 — Copyright © 2025 Spindox Labs
