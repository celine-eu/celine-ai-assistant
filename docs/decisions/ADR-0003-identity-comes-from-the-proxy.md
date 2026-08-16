# ADR-0003 — identity is established by the proxy, not by this service

**Date:** 2026-08-15
**Status:** accepted

## Context

Recorded after the fact: the code has worked this way since well before this ADR. It is
written down because the deployment assumption it carries is invisible from the source
and load-bearing.

Every CELINE service sits behind an `oauth2-proxy`. It can verify the caller's JWT
itself, against a JWKS discovered from the issuer, or it can trust the
`x-auth-request-*` headers the proxy attaches.

## Decision

Do both, token first: verify a token when one is present; otherwise accept the proxy's
headers when `OAUTH2_TRUST_HEADERS` is set, which it is by default.

The caller's own token is forwarded downstream unchanged — this service holds no service
account and each upstream re-verifies for itself. See ADR-0005.

## Consequences

**Anything that can reach this service's port and set `x-auth-request-user` and
`x-auth-request-groups` is whoever it claims to be, including an administrator.** What
makes that safe is network placement and the proxy stripping those headers from client
requests. Neither is verifiable from this repository, and no test can assert it.

A deployment that exposes this service directly is a full authentication bypass. That is
the cost of the decision, and it is why `OAUTH2_TRUST_HEADERS` exists as a switch rather
than being assumed.

Separately, the current implementation *falls back* to headers when a token is present
and fails to verify — which is not this decision, and is DEFECT-03.
