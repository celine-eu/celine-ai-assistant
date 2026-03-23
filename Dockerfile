# ── Build stage ──────────────────────────────────────────────────────────────
FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    UV_SYSTEM_PYTHON=1

WORKDIR /app

# Install uv
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && curl -LsSf https://astral.sh/uv/install.sh | sh

ENV PATH="/root/.local/bin:${PATH}"

# Copy manifests first — better layer caching
COPY pyproject.toml uv.lock README.md ./
COPY ./src ./src

# Install production deps into an isolated venv
RUN uv venv .venv && uv sync --no-editable --no-dev

# Copy application source
COPY ./alembic ./alembic
COPY ./alembic.ini ./alembic.ini

# ── Runtime stage ─────────────────────────────────────────────────────────────
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Match runAsUser: 1000 from the Helm chart podSecurityContext
RUN groupadd --gid 1000 appuser \
    && useradd --uid 1000 --gid 1000 --no-create-home appuser

WORKDIR /app

# Bring in only the built artefacts
COPY --from=builder --chown=appuser:appuser /app /app

# Runtime directories expected by the Helm chart
# - /app/data  → persistence.data.mountPath  (SQLite / local cache)
# - /app/qdrant → persistence.qdrant.mountPath (vector store)
# - /app/policies → policies.dir (OPA/Regorus policy files baked into image)
RUN mkdir -p /app/data /app/qdrant /app/policies \
    && chown -R appuser:appuser /app/data /app/qdrant /app/policies

USER appuser

ENV PATH="/app/.venv/bin:${PATH}"

EXPOSE 8012

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8012/health')"

CMD [ \
    "uvicorn", \
    "celine.assistant.main:create_app", \
    "--host", "0.0.0.0", \
    "--port", "8012" \
    ]
