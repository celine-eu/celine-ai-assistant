"""Alembic migration environment — async-compatible.

Supports both offline (SQL script generation) and online (live DB) modes.
The database URL is read from application settings so the same config works
across all deployment environments.

In online mode, the target database is created automatically if it doesn't
exist yet (useful for dev). In prod the DB already exists so this is a no-op.
"""

from __future__ import annotations

import asyncio
import logging
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool, text
from sqlalchemy.engine import Connection, make_url
from sqlalchemy.ext.asyncio import create_async_engine

from celine.assistant.db.models import Base
from celine.assistant.settings import settings

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

log = logging.getLogger(__name__)

target_metadata = Base.metadata


def _db_url() -> str:
    return settings.database_url


# ---------------------------------------------------------------------------
# Offline mode
# ---------------------------------------------------------------------------
def run_migrations_offline() -> None:
    context.configure(
        url=_db_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


# ---------------------------------------------------------------------------
# Online mode
# ---------------------------------------------------------------------------
def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def _ensure_database_exists(url: str) -> None:
    """Create the target database if it doesn't exist.

    Connects to the 'postgres' maintenance DB on the same host so we can
    issue a CREATE DATABASE without needing to be inside the target DB.
    Safe to call in prod — it's a no-op when the DB already exists.
    """
    u = make_url(url)
    target_db = u.database
    maintenance_url = u.set(database="postgres")

    engine = create_async_engine(
        maintenance_url,
        poolclass=pool.NullPool,
        isolation_level="AUTOCOMMIT",
    )
    try:
        async with engine.connect() as conn:
            result = await conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :db"),
                {"db": target_db},
            )
            if result.scalar():
                log.debug("database %r already exists", target_db)
            else:
                await conn.execute(text(f'CREATE DATABASE "{target_db}"'))
                log.info("created database %r", target_db)
    finally:
        await engine.dispose()


async def run_async_migrations() -> None:
    url = _db_url()
    await _ensure_database_exists(url)

    connectable = create_async_engine(url, poolclass=pool.NullPool)
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
