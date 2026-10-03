# Development

## Prerequisites

- Python >= 3.12
- `uv` package manager
- `task` (go-task)
- A running Qdrant instance
- PostgreSQL at `localhost:15432`

## Local Setup

```bash
uv sync
cp .env.example .env
# Set LLM_BASE_URL, LLM_CHAT_MODEL, LLM_EMBED_MODEL, DATABASE_URL, QDRANT_URL

uv run alembic upgrade head
task run
# Listens on http://localhost:8012
```

## Taskfile Commands

| Command | Description |
|---|---|
| `task test` | Run the test suite — needs no database, Qdrant, LLM or network |
| `task run` | Start dev server on port 8012 with reload |
| `task debug` | Start with debugger (port 48012) |
| `task setup` | Install dependencies with uv |
| `task alembic:migrate` | Apply all pending migrations |
| `task alembic:sync-model` | Generate new Alembic migration |
| `task alembic:reset` | Reset DB to base |
| `task release` | Run semantic-release |

## Docker Compose

```bash
docker compose up -d
```

Starts Qdrant, PostgreSQL, and the API container.

## Database Migrations

```bash
task alembic:migrate                     # apply pending
task alembic:sync-model                  # autogenerate new migration
task alembic:reset                       # downgrade to base
```

## Running Tests

```bash
uv run pytest -q
```

## Project Layout

```
src/celine/assistant/
  main.py                      # FastAPI app factory (create_app)
  routes.py                    # All route handlers
  settings.py                  # Pydantic-settings configuration
  auth.py                      # JWT verification (trusted headers or JWKS)
  rag.py                       # Per-community index, scoped retrieval, writes
  kb_collections.py            # Knowledge-base aliases, generations, embedding fingerprint
  kb_sources.py                # Git/directory sources: checkout and incremental indexing
  kb_store.py                  # Registered sources and their indexed document versions
  kb_admin.py                  # status, reindex, prune, migrate-legacy
  attachment_index.py          # Upload extraction and indexing (shared with rebuilds)
  cli.py                       # `celine-assistant kb …`
  history.py                   # Conversation and message persistence
  uploads.py                   # File upload storage and metadata
  openai_stream.py             # SSE streaming with agentic tool-calling loop
  openai_vision.py             # Image captioning via vision model
  llm.py                       # The model endpoint: clients, embeddings, startup check
  document_processing.py       # MIME detection and text extraction for uploads
  suggestions.py               # Localized prompt suggestions and tool labels
  models.py                    # Pydantic request/response models
  logging_.py                  # Logging configuration
  skills/
    base.py                    # Skill base class
    registry.py                # Skill registry (collects tools, dispatches calls)
    factory.py                 # Builds per-request skill registry from settings
    digital_twin.py            # Energy metrics, profile, assets (Digital Twin API)
    weather.py                 # Current weather, forecast, alerts, energy forecast
    flexibility.py             # Load-shift suggestions, gamification, commitments
    rec_registry.py            # REC profile, community, assets, delivery points
    documents.py               # Document search and attachment info (Qdrant)
    datasets.py                # Dataset queries (currently disabled)
  db/
    engine.py                  # SQLAlchemy async engine setup
    models.py                  # ORM: Conversation, Message, Attachment, KbSource, KbSourceDocument
alembic/                       # Database migrations
```
