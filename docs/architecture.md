# Architecture

## RAG Pipeline

The assistant processes user queries through a Retrieval-Augmented Generation pipeline:

1. **Upload** — files are uploaded via `POST /upload`, parsed, and chunked. Images are captioned via the vision model.
2. **Index** — chunks are embedded and stored in Qdrant as vector documents
3. **Chat** — at query time, relevant chunks are retrieved and injected into the OpenAI prompt; the LLM autonomously calls skill tools to fetch live data
4. **Stream** — the response is streamed back to the client via SSE

All of it shares **one Qdrant collection**: curated training material, administrator-shared
files, and every member's own uploads. What separates them is metadata that the retrieval
query does not currently read — see the companion's knowledge before
changing anything on this path.

## Component Overview

| Component | Module | Role |
|---|---|---|
| FastAPI application | `main.py` | HTTP server (`create_app` factory), route registration, lifespan hooks |
| RAG pipeline | `rag.py` | LlamaIndex index, retrieval, query engine |
| Auth | `auth.py` | JWT verification via trusted headers or JWKS |
| History | `history.py` | Conversation and message persistence |
| Uploads | `uploads.py` | File storage, attachment management |
| OpenAI streaming | `openai_stream.py` | SSE token streaming with agentic tool-calling loop |
| Vision | `openai_vision.py` | Image captioning via OpenAI vision model |
| Document processing | `document_processing.py` | MIME detection and text extraction for uploads |
| Skills | `skills/` | Modular skill system: Digital Twin, Weather, Flexibility, REC Registry, Documents |
| Suggestions | `suggestions.py` | Localized prompt suggestions and tool labels |
| Training materials | `training_materials.py` | Git clone/checkout **and** incremental indexing of the Markdown corpus |
| Qdrant setup | `qdrant_setup.py` | Collection initialization and management |
| Settings | `settings.py` | Pydantic-settings environment configuration |

### Modules that are not part of the pipeline

Present in `src/`, reachable from nothing, and easy to mistake for the supported path:

| Module | What it looks like | What it is |
|---|---|---|
| `ingest.py` | the way to index an uploaded file | uncalled. Uploads are indexed by `routes._process_upload` |
| `site_docs.py` | a second corpus ingester | a near-exact copy of `training_materials.py` |
| `training_materials_sync.py` | the sync entry point | an older one; the routes import `training_materials.py`'s |
| `src/celine/assistant/skills/datasets.py` | a dataset-query skill | deliberately disabled — `dataset-api` needs a service token, and this service holds only the caller's (ADR-0005) |

Deleting them is owed work, not a decision to re-take.

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
