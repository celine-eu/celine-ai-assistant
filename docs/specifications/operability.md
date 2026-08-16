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
