# Architecture

## RAG Pipeline

The assistant processes user queries through a Retrieval-Augmented Generation pipeline:

1. **Upload** — files are uploaded via `POST /upload`, parsed, and chunked. Images are captioned via the vision model.
2. **Index** — chunks are embedded and stored in Qdrant as vector documents
3. **Chat** — at query time, relevant chunks are retrieved and injected into the OpenAI prompt; the LLM autonomously calls skill tools to fetch live data
4. **Stream** — the response is streamed back to the client via SSE

## Component Overview

| Component | Module | Role |
|---|---|---|
| FastAPI application | `main.py` | HTTP server (`create_app` factory), route registration, lifespan hooks |
| RAG pipeline | `rag.py` | LlamaIndex index, retrieval, query engine |
| Ingestion | `ingest.py` | Parses uploads, splits into nodes, upserts to Qdrant |
| Auth | `auth.py` | JWT verification via trusted headers or JWKS |
| History | `history.py` | Conversation and message persistence |
| Uploads | `uploads.py` | File storage, attachment management |
| OpenAI streaming | `openai_stream.py` | SSE token streaming with agentic tool-calling loop |
| Vision | `openai_vision.py` | Image captioning via OpenAI vision model |
| Document processing | `document_processing.py` | MIME detection and text extraction for uploads |
| Skills | `skills/` | Modular skill system: Digital Twin, Weather, Flexibility, REC Registry, Documents |
| Suggestions | `suggestions.py` | Localized prompt suggestions and tool labels |
| Training materials | `training_materials.py` | Indexes Markdown training materials into Qdrant |
| Training materials sync | `training_materials_sync.py` | Git clone/pull for training materials repo |
| Site docs | `site_docs.py` | Indexes documentation site content |
| Qdrant setup | `qdrant_setup.py` | Collection initialization and management |
| Settings | `settings.py` | Pydantic-settings environment configuration |

## Frontend

This repository is a pure API backend. The chat UI is maintained separately in [celine-frontend](https://github.com/celine-eu/celine-frontend):

- `apps/assistant` — standalone full-page assistant app

The frontend communicates with this API at `apiBaseUrl`.

## Service Dependencies

| Service | Purpose |
|---|---|
| **OpenAI** | Chat completions, text embeddings, and vision (image captioning) |
| **Qdrant** | Vector storage and similarity search |
| **PostgreSQL** | Conversation history, attachment metadata |
| **Digital Twin** | Energy data, weather, and forecast queries via skills |
| **REC Registry** | Membership, assets, and delivery point queries via skills |
| **Flexibility API** | Load-shift suggestions and gamification via skills |
| **Keycloak / oauth2_proxy** | JWT authentication |

## Data Flow

Upload path:
```
POST /upload -> parse file -> (if image: caption via vision model) -> split into chunks -> embed (OpenAI) -> upsert (Qdrant) -> store metadata (PostgreSQL)
```

Chat path:
```
POST /chat -> verify JWT -> load history -> load authorized attachments -> retrieve context (Qdrant) -> build prompt -> stream (OpenAI SSE with agentic tool-calling loop)
```

## Database Models

PostgreSQL (async via SQLAlchemy + asyncpg). Alembic handles migrations. Models:

- `Conversation` — linked to a user identity from the JWT subject claim
- `Message` — role (`user`/`assistant`), content, timestamp, optional attachment refs
- `Attachment` — file metadata: name, MIME type, Qdrant collection reference, scope (user/system)
