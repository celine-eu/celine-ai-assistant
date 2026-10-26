# Conversations and chat

---

### REQ-0006 — a chat turn belongs to a conversation, named in the first event

A request without a `conversation_id` starts one. A request with an id the caller owns
continues it. An id the caller does not own is not an error and does not join anything:
the store looks up by id *and* user, so it starts a fresh conversation of the caller's
own. The id in use is the first thing the stream reports, in a `meta` event.

### REQ-0007 — a chat response is a server-sent event stream with a fixed frame

`meta`, then `sources` when `include_citations` is set, then the model's own events,
then `done`. `Cache-Control: no-cache` and `X-Accel-Buffering: no` are set so that no
proxy buffers the stream into a single delivery. A failure inside the model call is a
`error` event, not a broken connection or a non-200 status — by the time anything can go
wrong the response has already begun.

### REQ-0008 — the caller's message is persisted before the answer is produced

A turn that fails halfway must still leave the question in the history. A failure to
persist is logged and does not fail the turn.

### REQ-0009 — the answer is persisted once the stream completes

The text of the `token` events is accumulated and stored as one `assistant` message. An
empty answer is not stored.

### REQ-0010 — everything about a conversation is scoped to its user

Listing, reading messages and deleting are all filtered by user id (the `sub`,
REQ-0047). Another user's
conversation is reported as **not found**, never as forbidden: a `403` would confirm the
id exists.

### REQ-0011 — deleting is idempotent from the caller's view

A conversation that is not the caller's own — whether it belongs to somebody else or to
nobody — is `404`, and nothing is deleted.

### REQ-0012 — prior history is replayed to the model, minus the turn being answered

The route stores the caller's message and then reads the history back, so the last entry
is the message about to be answered; it is dropped before the history is sent. Only
`user` and `assistant` turns with non-empty content are replayed. When the replayed
history exceeds `CHAT_WORD_LIMIT` words, everything but the most recent
`CHAT_HOT_MESSAGES` turns is replaced with a model-written summary.

### REQ-0013 — paging bounds are clamped, not rejected

`limit` and `offset` are corrected into range and the values actually used are reported
back in the response.

At least one turn always stays out of the summary: `CHAT_HOT_MESSAGES` is floored at
one, because a configured zero would summarise nothing and drop nothing.

### REQ-0052 — generated text is marked as AI-generated on every way out

The assistant's answers are machine-marked as artificially generated (AI Act Art. 50(2)),
on each channel by which they leave the service:

- the `meta` event of `POST /chat` carries `ai_generated: true` and
  `generator: "celine-ai-assistant"` beside `conversation_id`;
- the `POST /chat` response carries the header `AI-Generated: true`;
- every `assistant` message returned by `GET /conversations/{id}/messages` carries
  `ai_generated: true`, and every `user` message `ai_generated: false`.

The mark is metadata, not a watermark in the text. No harmonised standard exists for
text; a statistical watermark needs control of the model's sampler and does not survive
editing, and C2PA describes media files, not a JSON stream. Metadata on every channel is
what is technically feasible for this service. The stored-message mark is derived from
the role: every `assistant` row is model output (REQ-0009).

### REQ-0053 — a stored answer records what produced it

So that a disputed answer can be investigated after the fact, an `assistant` message is
stored (REQ-0009) together with a trace of what produced it, in the `trace` column of the
same row:

- `model.requested`: the chat model the service asked for (`LLM_CHAT_MODEL`);
- `model.reported`: the model the endpoint named in its response (the stream's `model`
  field, the last one seen), and `model.fingerprint`: its `system_fingerprint`, when the
  endpoint sends one. Null when the endpoint says nothing. The model's version is
  whatever the endpoint reports here; the service has no other source for it;
- `service_version`: the assistant's own version, which fixes the system prompt and the
  tool definitions the model was given;
- `attachments`: the ids of the attachments given to the model with the question;
- `sources`: one entry per retrieved chunk given to the model, hidden ones included
  (REQ-0022): its `source`, its `score`, and the identifiers in its metadata that name
  what it came from (`kind`, `doc_id`, `source_id`, `attachment_id`). Not the text;
- `tools`: one entry per tool call, in the order they ran: the tool `name`, the
  `arguments` as the model sent them (the raw string when it is not valid JSON), and
  `failed: true` when the tool raised. Not the tool's result.

The trace lives and dies with its message: it is scoped to the same user, deleted with
the conversation (REQ-0011), and kept exactly as long as the conversation is. No route
returns it; `GET /conversations/{id}/messages` returns the same fields with or without
it. An operator reads it from the database. A `user` message has no trace, and neither
does an `assistant` message stored before this requirement: the column is null for both.

---

## Known limits

**Message timestamps are whole seconds.** `created_at` is `int(time.time())`, and both
the message ordering and the conversation listing order by it. Rows written inside one
second tie, so `last_snippet` is not guaranteed to be the last message and two
conversations touched in the same second come back in an arbitrary order.

Fixing it means finer timestamps or a sequence column — a schema change, and a units
change on a field the frontend reads. See DEFECT-16.
