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
# Set OPENAI_API_KEY, DATABASE_URL, QDRANT_URL

uv run alembic upgrade head
task run
# Listens on http://localhost:8012
```

## Taskfile Commands

| Command | Description |
|---|---|
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
  rag.py                       # LlamaIndex index, retriever, query engine
  ingest.py                    # File parsing and Qdrant ingestion
  history.py                   # Conversation and message persistence
  uploads.py                   # File upload storage and metadata
  openai_stream.py             # SSE streaming wrapper
  openai_vision.py             # Image captioning via vision model
  dashboard_context.py         # Digital Twin context enrichment
  training_materials.py        # Training materials indexing
  training_materials_sync.py   # Git sync for training materials
  site_docs.py                 # Documentation site content indexing
  qdrant_setup.py              # Qdrant collection initialization
  models.py                    # Pydantic request/response models
  logging_.py                  # Logging configuration
  db/
    engine.py                  # SQLAlchemy async engine setup
    models.py                  # ORM: Conversation, Message, Attachment
alembic/                       # Database migrations
```
