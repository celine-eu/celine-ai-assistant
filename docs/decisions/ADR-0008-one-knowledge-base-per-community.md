# ADR-0008 — one knowledge base per community, behind an alias per embedding model

**Date:** 2026-10-02
**Status:** accepted

## Context

One deployment serves several renewable energy communities, as onboarding already does.
Retrieval did not: every document lived in one Qdrant collection, scoped only `system` /
`user`, so a document an administrator shared was read by members of every REC, and the
only reference material was one git repository, the same for everyone.

Separately, changing the embedding model meant naming a new `QDRANT_COLLECTION` and
re-ingesting by hand — and nothing could re-ingest uploads, whose extracted text sat in
the database with no path back into the index.

## Decision

- **The community is the REC organization in the caller's token.** Its Keycloak alias is
  the community id (and the Digital Twin's). A member belongs to exactly one; a token
  naming several is refused rather than resolved. A REC's knowledge is managed by
  its own `managers` / `admins` organization groups or by a realm administrator — the
  rule onboarding applies — and an organization group never makes a realm administrator.
- **Each community has a knowledge base of its own**: a Qdrant alias
  `<QDRANT_COLLECTION>__<community_id>__<fingerprint>` over a timestamped collection.
  There is no shared corpus collection; reference material is a *source* — a git
  repository or a directory — registered for one community in the database.
- **The fingerprint hashes the embedding model and vector size.** Two models read two
  aliases, so a new model's knowledge bases are built while the old ones serve, and the
  deploy that changes `LLM_EMBED_MODEL` is the switch. The service refuses to start on a
  model no knowledge base was built for.
- **A rebuild never copies vectors.** `celine-assistant kb reindex` builds a new
  generation from the sources and the attachment rows, verifies it, and moves the alias in
  one operation; changes made during the build are reconciled after the move.
- **Legacy data moves by a command**, `kb migrate-legacy --community <id>`. No community
  id is a default in this repository, which is public.

## Consequences

- A member's retrieval touches one collection; the `community_id` metadata term stays in
  the filter as well, so a point in the wrong collection is still not returned.
- Every write path names a community. An upload by a caller with no REC is stored, not
  indexed; there is nowhere to index it.
- Operating the knowledge bases is a CLI in the service image, not a startup side
  effect: sources are registered and synced with `celine-assistant kb`, and
  `KB_SYNC_ON_START` is off by default. The infra chart's `TRAINING_MATERIALS_*` are read by
  nothing and are reported at startup until removed.
- Old generations accumulate until `kb prune`; that is the rollback window, and the cost.
- The upload API gained `community_id` on `/admin/uploads` (a realm administrator's), and
  `/admin/training-materials/sync` became `/admin/kb/sync`.
