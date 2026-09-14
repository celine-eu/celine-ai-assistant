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
headers when `OAUTH2_TRUST_HEADERS` is set.

**The switch is off by default** (changed 2026-09-14; it was on). The default identity is
a verified JWT and nothing else; trusting the `x-auth-request-*` headers is an explicit,
per-deployment opt-in, taken only where the network guarantees the proxy alone can set
them. A deployment relying on the header path must both turn the switch on and ensure the
proxy always forwards a verifiable token, or requests carrying none will be refused.

The caller's own token is forwarded downstream unchanged — this service holds no service
account and each upstream re-verifies for itself. See ADR-0005.

## Consequences

**Anything that can reach this service's port and set `x-auth-request-user` and
`x-auth-request-groups` is whoever it claims to be, including an administrator.** What
makes that safe is network placement and the proxy stripping those headers from client
requests. Neither is verifiable from this repository, and no test can assert it.

A deployment that exposes this service directly **and turns the switch on** is a full
authentication bypass. That is the cost of the header path, and it is why
`OAUTH2_TRUST_HEADERS` exists as a switch, and now defaults off rather than being assumed.

Separately, the current implementation *falls back* to headers when a token is present
and fails to verify — which is not this decision, and is DEFECT-03. (Fixed: a token that
fails to verify is now refused.)

**Token verification trusts only a configured anchor.** Verifying a token requires
`OAUTH2_JWKS_URL` (which falls back to the platform's `CELINE_OIDC_JWKS_URI`) or
`OAUTH2_ISSUER`; the service does not fetch keys from, or trust, the issuer a token names
for itself, and it pins the signature algorithm rather than reading it from the token
header. An earlier implementation did the opposite when those settings were unset —
deriving the JWKS location from the unverified token, skipping the issuer check, and
honouring the header's `alg` — which let a caller who could serve a key set forge any
identity. That is closed; a deployment with no trust anchor configured now refuses
tokens outright rather than trusting them.
