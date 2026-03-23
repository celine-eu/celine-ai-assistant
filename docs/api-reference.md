# API Reference

All endpoints require a valid JWT in the `Authorization: Bearer <token>` header unless noted otherwise. The OpenAPI schema is available at `http://localhost:8000/docs`.

## Chat

### `POST /chat`

Stream a chat response via Server-Sent Events.

**Request body:**

```json
{
  "message": "string",
  "conversation_id": "optional-uuid",
  "context": {"page": "dashboard"}
}
```

**Response:** `text/event-stream` — SSE tokens followed by a `[DONE]` sentinel.

**Behavior:**
- Creates a new conversation if `conversation_id` is omitted.
- Retrieves relevant document chunks from Qdrant before calling OpenAI.
- Persists the full assistant reply once streaming completes.

---

## Uploads and Attachments

### `POST /upload`

Upload a file for RAG ingestion.

**Request:** `multipart/form-data` with `file` field.

**Response:** `201` with attachment metadata including `id`, `filename`, `content_type`.

The file is parsed, chunked, embedded, and upserted into Qdrant. Raw file is stored in object storage.

### `GET /attachments`

List all attachments belonging to the authenticated user.

### `GET /attachments/{id}/raw`

Download the raw uploaded file.

### `DELETE /attachments/{id}`

Delete an attachment and remove its vectors from Qdrant.

---

## Conversations

### `GET /conversations`

List all conversations for the authenticated user. Returns `id`, `title`, `created_at`, `message_count`.

### `GET /conversations/{id}/messages`

Return all messages in a conversation.

### `DELETE /conversations/{id}`

Delete a conversation and all its messages.

---

## User

### `GET /user`

Return the authenticated user's profile derived from the JWT (`sub`, `email`, `name`).

---

## Admin

The following endpoints require the user to have admin group membership.

### `POST /admin/uploads`

List or inspect all uploads across all users (admin view).

### `POST /admin/ingest`

Re-index an existing attachment by ID. Useful after model changes.

### `POST /admin/reload`

Reload the LlamaIndex index from the current Qdrant state without restarting the service.

### `POST /admin/training-materials/sync`

Clone or refresh `celine-training-materials` inside the API container, check out the requested ref, and ingest Markdown files.

**Request body:**

```json
{
  "target_ref": "origin/main"
}
```

`target_ref` is optional. If omitted, the service uses `TRAINING_MATERIALS_REF`.

---

## Health

### `GET /health`

Returns `{"status": "ok"}`. No authentication required.
