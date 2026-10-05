# Identity and authorisation

This service authenticates nobody. It sits behind an `oauth2-proxy` and reads the
identity that proxy established — see ADR-0003 for why, and for the deployment
assumption that carries.

---

### REQ-0001 — every route but the health check requires an identity

A request that carries neither a usable token nor trusted identity headers is answered
`401`. `/health` is exempt, because a liveness probe reaches the container before any
proxy has attached anything to it.

### REQ-0002 — an access token is looked for in a fixed order, and must verify

`x-auth-request-access-token`, then an `Authorization: Bearer` header (matched
case-insensitively), then the cookie named by `OAUTH2_JWT_COOKIE_NAME` if one is
configured. The first that yields a value wins; a non-`Bearer` `Authorization` header is
ignored rather than rejected.

**A token that is found and does not verify is refused**, never downgraded to the
trusted headers. The headers are an identity for a request carrying no token at all —
otherwise an expired or forged token would be indistinguishable from no token, and with
`OAUTH2_TRUST_HEADERS` on that is whatever the caller asserted.

Verification is bound to a **configured** trust anchor. The key set comes from
`OAUTH2_JWKS_URL` (which falls back to the platform's `CELINE_OIDC_JWKS_URI`), or from
the OIDC discovery of `OAUTH2_ISSUER`; with neither set the token is refused rather than
verified against the issuer it names for itself. When `OAUTH2_ISSUER` is set, a token
whose `iss` differs is refused. The signature algorithm is taken from
`OAUTH2_ALGORITHMS` (default `RS256`), never from the token header. When
`OAUTH2_AUDIENCE` is set, the token must carry an `aud` that includes it: a token with
no `aud` at all is refused, not accepted for lack of anything to compare. A token must
carry `exp`, and `iss` when `OAUTH2_ISSUER` is set.

### REQ-0003 — trusted headers are an accepted identity

With `OAUTH2_TRUST_HEADERS` enabled, `x-auth-request-user` (or `x-auth-request-email`)
identifies the caller. **A header identity carries no grant**: `x-auth-request-groups` is
not read, so no header makes a platform administrator (REQ-0004) or names an
organization (REQ-0040). Platform roles come only from a verified token. **The switch is
off by default**: unless a deployment opts in,
headers alone are not an identity and a request carrying no verifiable token is answered
`401`. Outside dev a deployment cannot opt in: startup refuses the switch (REQ-0045).

### REQ-0004 — a platform administrator holds the `platform-admin` realm role

There are exactly two levels of authority, and they are never merged:

- **The platform:** a caller is a platform administrator exactly when the verified
  token's `realm_access.roles` contains `platform-admin`. That role is the only
  platform-wide grant.
- **An organization:** the groups in `organization.<alias>.groups` are valid only inside
  that organization (REQ-0005).

Nothing else makes a platform administrator. **Not** an `admins` group inside any
organization, which held that way made its holder an administrator of every REC (closed
2026-10-02). **Not** a realm group (top-level `groups` claim), which the platform no
longer uses: one still present in a token, `/admins` included, grants nothing. **Not** a
role with that name under `resource_access`, a top-level `roles` claim, or a trusted
header (REQ-0003). No user id is ever special-cased, and the role name is not
configurable.

`GET /user` reports `roles` (the caller's realm roles), `community_id`,
`is_platform_admin`, and `is_admin` — true for a platform administrator and for a
manager of the caller's own community (REQ-0005), which is what the UI gates its
administrator features on.

### REQ-0005 — a community's knowledge is managed by its managers

`POST /admin/uploads` and `POST /admin/kb/sync` act on one community. A caller may use
them for a community when they are a platform administrator (REQ-0004), or hold one of
`REC_MANAGER_GROUPS` (default `managers`, `admins`) **inside that REC's own
organization** — the rule onboarding applies. A group held in another organization says
nothing about this one. A manager acts on their own community; a platform administrator,
who has none, names one (`community_id`), and naming none is `400`.
Anyone else is answered `403` and the operation does not run.

### REQ-0040 — the caller's community is the one REC organization in their token

The community is the alias of the organization in the token's `organization` claim
whose type is `REC_ORGANIZATION_TYPE` (default `rec`), read flattened (`type`) first and
nested (`attributes.type`) second. The alias is also the Digital Twin community id.

| The token names | The caller's community |
|---|---|
| one REC organization | its alias |
| none (or only other organization types) | none: nothing is retrieved, uploads are stored and not indexed |
| more than one | **refused, `403`**, before anything is written. Choosing one would answer from one REC's documents to a member of another |

A trusted-header identity (ADR-0003) carries no organization claim and so has no
community.


