# ADR-0005 — the skill registry is built per request from the caller's token

**Date:** 2026-08-15
**Status:** accepted

## Context

Recorded after the fact. The assistant answers questions about a member's own energy
data, which lives in three services that each enforce their own authorisation. This
service could hold a service account and query on the member's behalf, or forward the
member's token and let each upstream decide.

## Decision

Forward the caller's token. `build_skill_registry` runs on every `/chat` and
`/suggestions` request and registers a skill only when both its upstream URL is
configured and a caller token is present.

## Consequences

This service has no privilege of its own to leak, and no authorisation logic duplicating
an upstream's. A member can never be shown another member's energy data, because the
token they presented would not fetch it.

The costs:

- **A missing capability is silent.** No token, or an unconfigured URL, removes skills
  and the request still succeeds — the model simply cannot answer. The absence is logged
  at warning level and that is the only signal.
- **`dataset-api` cannot be reached at all**, because it requires a service-level token.
  `DatasetSkill` is written and commented out in `factory.py` pending a token-exchange
  flow. That is the shape of the price.
- **A deployment that does not forward `x-auth-request-access-token` loses every upstream
  skill**, and with them every starter prompt. See DEFECT-15.
