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

Listing, reading messages and deleting are all filtered by user id. Another user's
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

---

## Known limits

**Message timestamps are whole seconds.** `created_at` is `int(time.time())`, and both
the message ordering and the conversation listing order by it. Rows written inside one
second tie, so `last_snippet` is not guaranteed to be the last message and two
conversations touched in the same second come back in an arbitrary order.

Fixing it means finer timestamps or a sequence column — a schema change, and a units
change on a field the frontend reads. See DEFECT-16.
