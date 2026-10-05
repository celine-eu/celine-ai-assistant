# Operability

---

### REQ-0034 — a failure is legible in the log and opaque in the response

Every unhandled exception is caught by the application's error boundary and answered
`500 Internal Server Error` with no detail; the traceback goes to the log. Log lines
carry `request_id` and `user_id`, defaulted to `-` by a filter so that a record made by a
library still formats.

**A log call must never be the failing statement.** `extra` keys are merged into the
`LogRecord` and Python raises on a collision with one of its own attributes — `filename`,
`module`, `name`, `args`, `message` among them. A logging call inside an `except` block
that collides takes down the handler that was meant to contain the problem.

A test scans every `extra={...}` in `src/` for a collision, so the next one fails a test
rather than a request.

### REQ-0045 — outside dev, startup refuses every development-only setting

The environment signal is `CELINE_ENV`, then `ENVIRONMENT`, then the legacy `APP_ENV`
(from the environment, or explicitly from `.env`); the first non-empty one wins. **Only
`dev` relaxes**: unset, empty, `prod`, `production`, `staging`, `test` or a typo is
hardened. `APP_ENV`'s own default is not a signal.

Hardened, startup refuses to run — before Qdrant or the database is reached, naming every
offending setting in one message — while any of these is in force:

- `OAUTH2_TRUST_HEADERS=true`, which makes unverified `x-auth-request-*` headers, groups
  included, an identity (REQ-0003);
- `OAUTH2_ISSUER` unset — with `OAUTH2_JWKS_URL` alone the token's `iss` is not checked;
- `QDRANT_API_KEY` unset;
- a `DATABASE_URL` carrying a development database password.

In dev the same list is logged as one warning and startup proceeds.

### REQ-0050 — every response carries the security headers

`X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY` and
`Referrer-Policy: no-referrer` on every response, errors included; and, on every
response that is not HTML, `Content-Security-Policy: default-src 'none';
frame-ancestors 'none'`. A route that sets its own policy keeps it (REQ-0049). The
interactive API docs are HTML that loads scripts, so they get no policy here.

### REQ-0046 — wildcard CORS is served in dev only

`Access-Control-Allow-Origin: *` (with credentials) is configured only when the signal of
REQ-0045 is `dev`. Anywhere else no cross-origin caller is allowed. On the same signal,
`/docs`, `/redoc` and `/openapi.json` are not mounted outside dev (`404`) unless
`CELINE_PUBLIC_DOCS=true`.
