"""A real database for the store that owns the SQL.

Everywhere else in this suite `HistoryStore` is replaced by `FakeHistoryStore`, which
means its queries — the correlated subqueries behind the conversation listing, the
ordering, the delete cascade — were executed by nothing at all. These run them.

**SQLite by default**, in a file under `tmp_path`, so `task test` still starts nothing.
A binary that reads a file is not a service, which is the same line already drawn around
`fsspec` and `git`. Production is PostgreSQL, and the dialects differ, so point these at
a real one when a query gets more interesting than the ones here:

    TEST_DATABASE_URL=postgresql+asyncpg://postgres:securepassword123@localhost:15432/ai_assistant \\
        task test -- tests/db

See ADR-0007.
"""

from __future__ import annotations

import os

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from celine.assistant.db import Base
from celine.assistant.history import HistoryStore

SCHEMA_URL = os.environ.get("TEST_DATABASE_URL")


@pytest.fixture
async def engine(tmp_path):
    url = SCHEMA_URL or f"sqlite+aiosqlite:///{tmp_path / 'history.db'}"
    engine = create_async_engine(url, future=True)

    async with engine.begin() as conn:
        if conn.dialect.name == "sqlite":
            # SQLite does not enforce foreign keys unless asked, and the messages table
            # declares `ON DELETE CASCADE`. Without this the constraint is decoration.
            await conn.execute(text("PRAGMA foreign_keys=ON"))
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture
def session_factory(engine):
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture
def clock(monkeypatch):
    """Control what `HistoryStore` stamps rows with.

    `created_at` is `int(time.time())`, and several behaviours here turn on whether two
    rows share a value. Leaving that to the wall clock makes the tests flaky in both
    directions — they would pass or fail on whether the writes straddled a second.
    """
    from celine.assistant import history as history_module

    class Clock:
        def __init__(self) -> None:
            self.now = 1_700_000_000.0

        def time(self) -> float:
            return self.now

        def advance(self, seconds: float) -> None:
            self.now += seconds

    fake = Clock()
    monkeypatch.setattr(history_module, "time", fake)
    return fake


@pytest.fixture
def store(session_factory, clock) -> HistoryStore:
    """The real store, pointed at the test database.

    This is the seam `HistoryStore.__init__` exists for. Before it, every method reached
    the module-level `AsyncSessionLocal` and the only way to test any of this was not to.
    """
    return HistoryStore(session_factory=session_factory)
