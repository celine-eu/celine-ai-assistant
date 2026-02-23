"""Async SQLAlchemy engine and session factory — PostgreSQL (asyncpg).

Configuration
-------------
Set the DATABASE_URL environment variable (required)::

    DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/celine

Optional pool tuning via env vars (all have sensible defaults):

    DB_POOL_SIZE=10
    DB_MAX_OVERFLOW=20
    DB_POOL_TIMEOUT=30
    DB_POOL_RECYCLE=1800
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from celine.assistant.settings import settings

engine = create_async_engine(
    settings.database_url,  # must be postgresql+asyncpg://...
    echo=settings.app_env == "dev",
    pool_pre_ping=True,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
    pool_timeout=settings.db_pool_timeout,
    pool_recycle=settings.db_pool_recycle,
)

AsyncSessionLocal: async_sessionmaker[AsyncSession] = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)
