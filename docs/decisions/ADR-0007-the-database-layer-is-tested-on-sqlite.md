# ADR-0007 — the store's SQL is tested on SQLite by default and PostgreSQL in CI

**Date:** 2026-08-15
**Status:** accepted

## Context

ADR-0001 put every external dependency behind a fake, and named the cost: `HistoryStore`'s
SQL — three correlated subqueries, an ordering, a delete cascade, two scoping clauses —
was executed by nothing at all. The API suite ran against `FakeHistoryStore`, which
reimplements the intent and therefore agrees with itself.

Closing it needed two things. `HistoryStore` reached the module-level `AsyncSessionLocal`
directly, so there was no seam to point it anywhere; and running the tests needed a
database, which ADR-0001 says the default suite must not.

## Decision

`HistoryStore.__init__` takes an optional `session_factory`, defaulting to the
application's. Routes reach the store through a `get_history_store` dependency rather
than `request.app.state`, so a test overrides it the way `../dataset-api` overrides its
sessions.

`tests/db/` runs the real store against **SQLite in a `tmp_path` file** by default — a
binary reading a file, which is the same line already drawn around `fsspec` and `git`, so
`task test` still starts nothing. `TEST_DATABASE_URL` points the same tests at
PostgreSQL, and CI runs them both ways.

CI additionally applies the migrations from empty and runs `alembic check`, because the
store's tests build the schema with `create_all` and so say nothing about whether the
migrations produce it.

## Consequences

The queries are executed, and the first run of them found that `last_snippet` is not
reliably the last message and that the conversation ordering ties — neither of which the
double does, because the double is written from the intent. That gap is the whole reason
this ADR exists, and it is recorded as DEFECT-16.

The costs:

- **Two dialects, one default.** SQLite and PostgreSQL disagree about tie ordering,
  integer widths and foreign-key enforcement — the fixture turns `PRAGMA foreign_keys`
  on because otherwise `ON DELETE CASCADE` is decoration. A query that leans on anything
  dialect-specific will pass locally and fail in CI, which is the right way round but is
  still a surprise the playbook has to warn about.
- **Two stores to keep in step.** `FakeHistoryStore` is still what the API suite uses,
  so it can still drift. `tests/unit/test_history_contract.py` holds the signatures and
  `tests/db/` now holds two differential tests; neither is a substitute for deleting the
  double, which would mean a database in every test run.

What will tempt someone to undo this: a query that SQLite cannot run. The answer then is
to mark that test PostgreSQL-only, not to make the whole suite need a service.
