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
- Enriches the prompt with dashboard context from Digital Twin if configured.
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

Return the authenticated user's profile derived from the JWT.

---

## Admin

The following endpoints require the user to be a member of the admin group.

### `POST /admin/uploads`

Upload a file as a system-level attachment (visible to all users).

### `POST /admin/training-materials/sync`

Clone or refresh `celine-training-materials` inside the container, check out the requested ref, and ingest Markdown files.

---

## Health

### `GET /health`

Returns `{"status": "ok"}`. No authentication required.
