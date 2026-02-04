from __future__ import annotations

from typing import Any

from .rag import upsert_documents_from_file


async def ingest_file(
    *,
    local_path: str,
    source_uri: str,
    scope: str,
    owner_user_id: str | None,
    original_filename: str,
    content_type: str | None,
) -> dict[str, Any]:
    metadata = {
        "source_uri": source_uri,
        "filename": original_filename,
        "content_type": content_type,
        "scope": scope,
        "owner_user_id": owner_user_id,
    }
    result = await upsert_documents_from_file(local_path=local_path, metadata=metadata)
    return {"status": "indexed", "result": result}
