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

### REQ-0003 — trusted headers are an accepted identity

With `OAUTH2_TRUST_HEADERS` enabled, `x-auth-request-user` (or `x-auth-request-email`)
identifies the caller and `x-auth-request-groups` carries their groups, comma-separated,
with blank entries dropped. With the switch off, headers alone are not an identity.

### REQ-0004 — administrator status is group membership

A caller is an administrator exactly when their groups contain `ADMIN_GROUP`. Groups are
read from the top-level `groups` claim and from `organization.<alias>.groups`, with a
leading `/` stripped from each. No user id is ever special-cased.

### REQ-0005 — administrator routes refuse everyone else

`POST /admin/uploads` and `POST /admin/training-materials/sync` answer `403` to an
identified non-administrator, and the underlying operation does not run.


