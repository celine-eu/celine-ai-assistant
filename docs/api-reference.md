# API Reference

All endpoints require a valid JWT unless noted otherwise. The JWT is read from the `x-auth-request-access-token` header (oauth2_proxy) or `Authorization: Bearer` header. OpenAPI docs at `http://localhost:8012/docs`.

## Chat

### `POST /chat`

Stream a chat response via Server-Sent Events.

**Request body:**

```json
{
  "message": "string",
  "conversation_id": "optional-uuid",
  "attachment_ids": ["optional-list-of-uuids"],
  "context": {"page": "dashboard"},
  "top_k": 5,
  "include_citations": false
}
```

**Response:** `text/event-stream` — SSE events with `data: {"type": "<type>", "data": ...}` format.

**Behavior:**
- Creates a new conversation if `conversation_id` is omitted.
- Loads authorized attachments and retrieves relevant document chunks from Qdrant.
- The LLM autonomously invokes registered skills (energy data, weather, flexibility, etc.) via tool calls.
- Persists the full assistant reply once streaming completes.

---

## Uploads and Attachments

### `POST /upload`

Upload a file for RAG ingestion (user scope).

**Request:** `multipart/form-data` with `file` field.

**Response:** `201` with attachment metadata including `id`, `filename`, `content_type`.

Images are captioned via the vision model before chunking. All files are parsed, chunked, embedded, and upserted into Qdrant.

### `GET /attachments`

List all attachments belonging to the authenticated user.

### `GET /attachments/{id}/raw`

Download the raw uploaded file.

### `DELETE /attachments/{id}`

Delete an attachment and remove its vectors from Qdrant.

---

## Conversations

### `GET /conversations`

List all conversations for the authenticated user.

### `GET /conversations/{id}/messages`

Return all messages in a conversation.

### `DELETE /conversations/{id}`

Delete a conversation and all its messages.

---

## User

### `GET /user`

Return the authenticated user's profile derived from the JWT: `community_id` (the REC
organization in the token, or `null`), `roles` (the caller's realm roles, from
`realm_access.roles`), `is_platform_admin` (holds the `platform-admin` realm role), and
`is_admin` — true for a platform administrator and for a manager of the caller's own
community. An identity from trusted headers has no roles.

---

## Admin

These act on one community's knowledge base. The caller must be a platform administrator
(the `platform-admin` realm role in a verified token's `realm_access.roles`) or hold one of
`REC_MANAGER_GROUPS` inside that REC's organization. A realm group (top-level `groups`
claim) grants nothing. A manager acts on their own community; a platform administrator
names one with `community_id` (`400` without). Anyone else gets `403`.

### `POST /admin/uploads`

Multipart: `file`, and optionally `community_id` (a platform administrator's). Shares a file
with the community as a system-scoped attachment, readable by its members.

### `POST /admin/kb/sync`

Body: `{"community_id": "…" | null, "full": false}`. Syncs every source registered for
the community and returns one result per source; a failing source carries an `error`
and does not stop the others. Replaces `POST /admin/training-materials/sync`.

---

## Health

### `GET /health`

Returns `{"status": "ok"}`. No authentication required.

### `GET /ping`

Returns `{"ok": true}`. Requires authentication — useful as a liveness check that validates the JWT.
