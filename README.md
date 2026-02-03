# celine-chatbot-api (v2)

Changes vs v1:
- plain logging (no JSON logger)
- document source via `DOCS_URI` using fsspec (local path or s3://)
- chat history stored in sqlite (`CHAT_DB_PATH`), keyed by `user_id` + `conversation_id`

## Run

```bash
cd backend
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

## Docs URI

- Local:
  - `DOCS_URI=/path/to/docs`
  - `DOCS_URI=file:///path/to/docs`
- MinIO/S3:
  - `DOCS_URI=s3://bucket/prefix/`
  - set `S3_ENDPOINT_URL`, `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY`
