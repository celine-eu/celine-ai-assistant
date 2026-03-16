# Development

## Prerequisites

- Python ≥ 3.11
- Docker and Docker Compose
- `uv` package manager
- A running Qdrant instance
- A running PostgreSQL instance

## Local Setup

```bash
# Clone and enter the repo
cd celine-ai-assistant

# Install dependencies
uv sync

# Copy and edit the environment file
cp .env.example .env
# Set OPENAI_API_KEY, DATABASE_URL, JWKS_URL, QDRANT_URL
```

## Start Services via Docker Compose

```bash
# Start Qdrant + PostgreSQL
docker compose up -d qdrant db

# Run database migrations
uv run alembic upgrade head

# Start the API
uv run uvicorn celine.assistant.main:app --reload --host 0.0.0.0 --port 8000
```

## Full Stack via Docker

```bash
docker compose up -d
```

This starts: `db` (PostgreSQL), `qdrant`, and `api` (the assistant).

## Database Migrations

Migrations are managed with Alembic:

```bash
# Apply all pending migrations
uv run alembic upgrade head

# Create a new migration
uv run alembic revision --autogenerate -m "describe change"

# Downgrade one step
uv run alembic downgrade -1
```

## Running Tests

```bash
uv run pytest -q
```

Tests use an in-memory or test-configured database and mock OpenAI/Qdrant calls.

## Project Layout

```
src/celine/assistant/
├── auth.py           # JWT verification, identity extraction
├── db/
│   ├── engine.py     # SQLAlchemy async engine setup
│   └── models.py     # ORM models: Conversation, Message, Attachment
├── docs_source.py    # Document source abstraction for RAG
├── history.py        # Conversation and message persistence
├── ingest.py         # File parsing and Qdrant ingestion
├── main.py           # FastAPI app factory, lifespan, router registration
├── models.py         # Pydantic request/response models
├── openai_stream.py  # SSE streaming wrapper for LlamaIndex
├── openai_vision.py  # Vision/image attachment handling
├── qdrant_setup.py   # Qdrant collection initialization
├── rag.py            # LlamaIndex index, retriever, query engine
├── routes.py         # FastAPI route handlers
├── settings.py       # pydantic-settings configuration
└── uploads.py        # File upload storage and metadata
```
