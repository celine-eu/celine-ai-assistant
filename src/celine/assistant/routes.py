from __future__ import annotations

import asyncio
import json
import logging
from typing import AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File
from fastapi.responses import StreamingResponse

from celine.assistant.ingest import ingest_file

from .auth import UserInfo, get_user_identity, UserIdentity, is_admin
from .models import ChatRequest, HealthResponse
from .rag import build_retriever, retrieve, node_to_source
from .openai_stream import stream_chat
from .uploads import store_upload, open_upload_stream, delete_upload
from .settings import settings

log = logging.getLogger(__name__)

router = APIRouter()
_retriever = build_retriever()


def _sse(event_type: str, data) -> str:
    payload = {"type": event_type, "data": data}
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def require_admin(user: UserIdentity = Depends(get_user_identity)) -> UserIdentity:
    if not is_admin(user):
        raise HTTPException(status_code=403, detail="Admin only")
    return user


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(status="ok")


async def _read_upload_or_413(file: UploadFile) -> bytes:
    data = await file.read()
    max_bytes = max(1, settings.max_upload_mb) * 1024 * 1024
    if len(data) > max_bytes:
        raise HTTPException(
            status_code=413, detail=f"File too large (max {settings.max_upload_mb}MB)"
        )
    return data


@router.post("/upload")
async def upload_user(
    request: Request,
    file: UploadFile = File(...),
    user: UserIdentity = Depends(get_user_identity),
):
    data = await _read_upload_or_413(file)

    stored = await store_upload(
        scope="user",
        owner_user_id=user.user_id,
        filename=file.filename or "upload",
        content_type=file.content_type,
        data=data,
    )

    att_id = await request.app.state.history_store.record_attachment(
        scope="user",
        owner_user_id=user.user_id,
        uri=stored.uri,
        path=stored.path,
        filename=stored.filename,
        content_type=stored.content_type,
        size_bytes=stored.size_bytes,
    )

    if stored.uri.startswith("file://"):
        local_path = stored.uri[len("file://") :]
        await ingest_file(
            local_path=local_path,
            source_uri=stored.uri,
            scope="user",
            owner_user_id=user.user_id,
            original_filename=stored.filename,
            content_type=stored.content_type,
        )

    return {
        "status": "indexed",
        "attachment_id": att_id,
        "uri": stored.uri,
        "filename": stored.filename,
        "content_type": stored.content_type,
        "size": stored.size_bytes,
        "scope": "user",
    }


@router.post("/admin/uploads")
async def upload_system(
    request: Request,
    file: UploadFile = File(...),
    admin: UserIdentity = Depends(require_admin),
):
    data = await _read_upload_or_413(file)

    stored = await store_upload(
        scope="system",
        owner_user_id=None,
        filename=file.filename or "upload",
        content_type=file.content_type,
        data=data,
    )

    att_id = await request.app.state.history_store.record_attachment(
        scope="system",
        owner_user_id=None,
        uri=stored.uri,
        path=stored.path,
        filename=stored.filename,
        content_type=stored.content_type,
        size_bytes=stored.size_bytes,
    )

    if stored.uri.startswith("file://"):
        local_path = stored.uri[len("file://") :]
        await ingest_file(
            local_path=local_path,
            source_uri=stored.uri,
            scope="system",
            owner_user_id=None,
            original_filename=stored.filename,
            content_type=stored.content_type,
        )

    return {
        "status": "indexed",
        "attachment_id": att_id,
        "uri": stored.uri,
        "filename": stored.filename,
        "content_type": stored.content_type,
        "size": stored.size_bytes,
        "scope": "system",
    }


@router.get("/attachments")
async def list_attachments(
    request: Request,
    user: UserIdentity = Depends(get_user_identity),
    limit: int = 200,
):
    items = await request.app.state.history_store.list_attachments_for_user(
        user.user_id, limit=limit
    )
    return {"items": items, "limit": limit}


async def _get_attachment_authorized(
    request: Request, user: UserIdentity, attachment_id: str
):
    att = await request.app.state.history_store.get_attachment_any(attachment_id)
    if not att:
        raise HTTPException(status_code=404, detail="Attachment not found")

    if att["scope"] == "system":
        return att

    if att["scope"] == "user":
        if att.get("owner_user_id") == user.user_id or is_admin(user):
            return att
        raise HTTPException(status_code=403, detail="Forbidden")

    raise HTTPException(status_code=500, detail="Invalid attachment scope")


@router.get("/attachments/{attachment_id}/raw")
async def get_attachment_raw(
    attachment_id: str,
    request: Request,
    user: UserIdentity = Depends(get_user_identity),
):
    att = await _get_attachment_authorized(request, user, attachment_id)

    ct = att.get("content_type") or "application/octet-stream"
    headers = {"Content-Disposition": f'inline; filename="{att.get("filename")}"'}

    return StreamingResponse(
        open_upload_stream(att["path"]),
        media_type=ct,
        headers=headers,
    )


@router.delete("/attachments/{attachment_id}")
async def delete_attachment(
    attachment_id: str,
    request: Request,
    user: UserIdentity = Depends(get_user_identity),
):
    att = await request.app.state.history_store.get_attachment_any(attachment_id)
    if not att:
        raise HTTPException(status_code=404, detail="Attachment not found")

    if att["scope"] == "system" and not is_admin(user):
        raise HTTPException(status_code=403, detail="Admin only")

    if (
        att["scope"] == "user"
        and (att.get("owner_user_id") != user.user_id)
        and not is_admin(user)
    ):
        raise HTTPException(status_code=403, detail="Forbidden")

    await request.app.state.history_store.delete_attachment_any(attachment_id)

    try:
        await delete_upload(att["path"])
    except Exception:
        log.exception("attachments_delete_blob_failed", extra={"path": att.get("path")})

    return {"status": "deleted", "attachment_id": attachment_id}


@router.get("/user")
async def get_user(
    request: Request,
    user: UserIdentity = Depends(get_user_identity),
) -> UserInfo:
    return UserInfo.from_identity(user)


@router.post("/chat")
async def chat(
    req: ChatRequest,
    request: Request,
    user: UserIdentity = Depends(get_user_identity),
):
    conv = await request.app.state.history_store.get_or_create_conversation(
        user.user_id, req.conversation_id
    )

    try:
        await request.app.state.history_store.append_message(
            user.user_id, conv.conversation_id, "user", req.message
        )
    except Exception:
        log.exception("history_append_user_failed")

    nodes = await asyncio.to_thread(retrieve, _retriever, req.message, req.top_k)
    sources = [node_to_source(n) for n in nodes]

    async def gen() -> AsyncGenerator[str, None]:
        assistant_text_parts: list[str] = []
        yield _sse("meta", {"conversation_id": conv.conversation_id})
        if req.include_citations:
            yield _sse("sources", sources)

        async for tok in stream_chat(user_message=req.message, context_blocks=sources):
            assistant_text_parts.append(tok)
            yield _sse("token", tok)

        try:
            await request.app.state.history_store.append_message(
                user.user_id,
                conv.conversation_id,
                "assistant",
                "".join(assistant_text_parts),
            )
        except Exception:
            log.exception("history_append_assistant_failed")

        yield _sse("done", None)

    return StreamingResponse(gen(), media_type="text/event-stream")
