# ADR-0001 — the test suite fakes every external boundary

**Date:** 2026-08-15
**Status:** accepted

## Context

This service owns almost nothing it talks to. The skills reach three platform APIs
through `celine-sdk`; retrieval reaches Qdrant and an embedding model; the agentic loop
reaches an LLM; history is in PostgreSQL behind Alembic. A test that asserts anything
about this repository has to decide what it is willing to run.

Two conventions already existed in the workspace. `../dataset-api` runs its suite against
a real PostgreSQL, creating and dropping a schema per run. `../ontologies` is pure. The
alternatives considered were: fake at the `celine-sdk` client objects (cheap, blind to
SDK drift), fake at HTTP with a transport stub (survives an SDK bump, much larger), or
record real responses (tests the prompts too, and rots).

## Decision

Fake at the narrowest boundary for each dependency, and require the suite to run with
**no external service at all**: no database, no Qdrant, no LLM, no network.

- `celine-sdk` clients are replaced with objects shaped like their responses.
- The LLM is replaced at `client.chat.completions.create`.
- Retrieval is replaced at `rag.build_retriever` and `rag.retrieve`.
- PostgreSQL is replaced with `FakeHistoryStore` on `app.state`.
- Storage is **not** faked: `fsspec` on a temp directory is a filesystem, not a service.
  Nor is `git`, for the same reason.

## Consequences

The suite runs in under four seconds anywhere, which is what makes "establish the
baseline first" a rule people follow rather than one they skip.

It cannot see three things, and each is stated where it will be read rather than only
here:

- **SDK drift.** A `celine-sdk` bump can leave the suite green and the service broken.
  `.agents/knowledge/faking-the-sdk-boundary.md`.
- **SQL.** `HistoryStore`'s ordering, subqueries and delete cascade are executed by
  nothing. `.agents/playbooks/testing.md` says not to report a change to `history.py` as
  verified by `task test`.
- **Prompts.** A faked model tests the loop and not what the model does with the words.

What will tempt someone to undo this: the first production bug in `HistoryStore`'s SQL.
The right answer then is a second, marked, database-backed layer — not making the fast
layer slow.
