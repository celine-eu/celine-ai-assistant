# Architecture

## RAG Pipeline

The assistant processes user queries through a Retrieval-Augmented Generation pipeline:

1. **Upload** — files are uploaded via `POST /upload`, parsed, and chunked
2. **Index** — chunks are embedded and stored in Qdrant as vector documents
3. **Chat** — at query time, relevant chunks are retrieved and injected into the OpenAI prompt
4. **Stream** — the response is streamed back to the client via SSE

## Component Overview

| Component | Module | Role |
|---|---|---|
| FastAPI application | `main.py` | HTTP server, route registration, lifespan hooks |
| RAG pipeline | `rag.py` | LlamaIndex index, retrieval, query engine |
| Ingestion | `ingest.py` | Parses uploads, splits into nodes, upserts to Qdrant |
| Auth | `auth.py` | JWKS-based JWT verification, identity extraction |
| History | `history.py` | Conversation and message persistence |
| Uploads | `uploads.py` | File storage, attachment management |
| OpenAI streaming | `openai_stream.py` | SSE token streaming with LlamaIndex |
| Vision | `openai_vision.py` | Image attachment support in chat messages |
| Qdrant setup | `qdrant_setup.py` | Collection initialization and management |
| Settings | `settings.py` | Pydantic-settings environment configuration |

## Frontend

This repository is a pure API backend. The chat UI is maintained separately in [celine-frontend](https://github.com/celine-eu/celine-frontend):

- `packages/assistant-ui` — `@celine-eu/assistant-ui` Svelte component library (ChatCore, AssistantWidget, etc.)
- `apps/assistant` — standalone full-page assistant app

The frontend communicates with this API at `apiBaseUrl`. When deployed inside the participant webapp, requests are proxied through the `celine-webapp` BFF.

## Service Dependencies

| Service | Purpose |
|---|---|
| **OpenAI** | Chat completions and text embeddings |
| **Qdrant** | Vector storage and similarity search |
| **PostgreSQL** | Conversation history and attachment metadata |
| **S3 / object storage** | Raw file storage for uploads |
| **Keycloak / JWKS endpoint** | JWT public key discovery for auth |

## Data Flow

Upload path:
```
POST /upload → parse file → split into chunks → embed (OpenAI) → upsert (Qdrant) → store metadata (PostgreSQL)
```

Chat path:
```
POST /chat → verify JWT → load history → retrieve context (Qdrant) → build prompt → stream (OpenAI SSE)
```

## Database Models

Conversations and messages are stored in PostgreSQL using SQLAlchemy async models. Alembic handles schema migrations. The `db/models.py` module defines:

- `Conversation` — linked to a user identity from the JWT subject claim
- `Message` — role (`user`/`assistant`), content, timestamp, optional attachment refs
- `Attachment` — file metadata: name, MIME type, Qdrant collection reference
