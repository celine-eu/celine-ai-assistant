from __future__ import annotations

import asyncio
import json
import uuid
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
from .openai_vision import describe_image
from .rag import upsert_documents_from_text

log = logging.getLogger(__name__)

router = APIRouter()
_retriever = build_retriever()


def _sse(event_type: str, data) -> str:
    payload = {"type": event_type, "data": data}
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


async def _load_authorized_attachments(
    request: Request,
    user: UserIdentity,
    attachment_ids: list[str],
) -> list[dict]:
    out: list[dict] = []
    for att_id in attachment_ids:
        att = await request.app.state.history_store.get_attachment_any(att_id)
        if not att:
            continue

        if att["scope"] == "system":
            out.append(att)
            continue

        if att["scope"] == "user":
            if att.get("owner_user_id") == user.user_id or is_admin(user):
                out.append(att)
                continue

        raise HTTPException(status_code=403, detail="Forbidden attachment access")
    return out


def _attachment_context_block(atts: list[dict]) -> dict:
    lines: list[str] = []
    for a in atts:
        fn = a.get("filename") or "file"
        ct = a.get("content_type") or ""
        scope = a.get("scope")
        caption = (a.get("caption") or "").strip()

        lines.append(f"- filename: {fn}")
        if ct:
            lines.append(f"  content_type: {ct}")
        lines.append(f"  scope: {scope}")
        if caption:
            lines.append(f"  description: {caption}")
        else:
            lines.append("  description: (no description available)")

    text = (
        "User attached the following files. Treat these as highly relevant context for this message:\n"
        + "\n".join(lines)
    )

    return {
        "source": "attached_files",
        "title": "Attached files",
        "text": text,
        "score": 1.0,
        "metadata": {"kind": "attachment_context"},
    }


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


def _is_image(filename: str, content_type: str | None) -> bool:
    if content_type and content_type.startswith("image/"):
        return True
    return filename.lower().endswith(
        (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tiff", ".tif")
    )


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

    caption: str | None = None
    if _is_image(stored.filename, stored.content_type):
        caption = await describe_image(image_bytes=data)

    att_id = await request.app.state.history_store.record_attachment(
        scope="user",
        owner_user_id=user.user_id,
        uri=stored.uri,
        path=stored.path,
        filename=stored.filename,
        content_type=stored.content_type,
        size_bytes=stored.size_bytes,
        caption=caption,
    )

    if caption:
        await upsert_documents_from_text(
            text=f"Image description for {stored.filename}:\n{caption}",
            metadata={
                "attachment_id": att_id,
                "source_uri": stored.uri,
                "filename": stored.filename,
                "content_type": stored.content_type,
                "scope": "user",
                "owner_user_id": user.user_id,
                "kind": "image_caption",
            },
        )

    return {
        "status": "indexed" if caption else "stored",
        "attachment_id": att_id,
        "uri": stored.uri,
        "filename": stored.filename,
        "content_type": stored.content_type,
        "size": stored.size_bytes,
        "scope": "user",
        "caption": caption,
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

    caption: str | None = None
    if _is_image(stored.filename, stored.content_type):
        caption = await describe_image(image_bytes=data)

    att_id = await request.app.state.history_store.record_attachment(
        scope="system",
        owner_user_id=None,
        uri=stored.uri,
        path=stored.path,
        filename=stored.filename,
        content_type=stored.content_type,
        size_bytes=stored.size_bytes,
        caption=caption,
    )

    if caption:
        await upsert_documents_from_text(
            text=f"System image description for {stored.filename}:\n{caption}",
            metadata={
                "attachment_id": att_id,
                "source_uri": stored.uri,
                "filename": stored.filename,
                "content_type": stored.content_type,
                "scope": "system",
                "owner_user_id": None,
                "kind": "image_caption",
            },
        )

    return {
        "status": "indexed" if caption else "stored",
        "attachment_id": att_id,
        "uri": stored.uri,
        "filename": stored.filename,
        "content_type": stored.content_type,
        "size": stored.size_bytes,
        "scope": "system",
        "caption": caption,
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

    attached = await _load_authorized_attachments(request, user, req.attachment_ids)
    attachment_block = _attachment_context_block(attached) if attached else None

    nodes = await asyncio.to_thread(retrieve, _retriever, req.message, req.top_k)
    sources = [node_to_source(n) for n in nodes]

    if attachment_block:
        sources = [attachment_block, *sources]

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


@router.get("/conversations")
async def list_conversations(
    request: Request,
    user: UserIdentity = Depends(get_user_identity),
    limit: int = 50,
    offset: int = 0,
):
    # Basic bounds to avoid accidental abuse
    limit = max(1, min(int(limit), 200))
    offset = max(0, int(offset))

    items = await request.app.state.history_store.list_conversations(
        user.user_id, limit=limit, offset=offset
    )
    return {"items": items, "limit": limit, "offset": offset}


@router.get("/conversations/{conversation_id}/messages")
async def conversation_messages(
    conversation_id: str,
    request: Request,
    user: UserIdentity = Depends(get_user_identity),
    limit: int = 200,
):
    limit = max(1, min(int(limit), 500))

    # Ensure conversation exists for this user; otherwise 404
    convs = await request.app.state.history_store.list_conversations(
        user.user_id, limit=1, offset=0
    )
    # Cheap existence check: ask store for messages; if no conversation row exists, list_messages just returns empty.
    # We want 404 if conversation doesn't belong to user.
    #
    # Implement strict ownership check by attempting a get_or_create with provided id:
    # If it doesn't exist for this user, store will create it (bad).
    # So we instead check with list_conversations using a direct query isn't available.
    #
    # Therefore: add a lightweight existence check via delete_conversation logic approach:
    # We'll query messages; if empty we still can't know if conversation exists. So use the DB-backed check:
    # HistoryStore currently doesn't expose "conversation exists" — so we treat "no messages + not in list" as 404
    # by scanning recent conversations (bounded) OR implement a new store method later.

    # Bounded scan: check existence in the first 200 conversations (enough for UI usage)
    exists = False
    page = await request.app.state.history_store.list_conversations(
        user.user_id, limit=200, offset=0
    )
    exists = any(c.get("conversation_id") == conversation_id for c in page)
    if not exists:
        raise HTTPException(status_code=404, detail="Conversation not found")

    messages = await request.app.state.history_store.list_messages(
        user.user_id, conversation_id, limit=limit
    )
    return {"messages": messages, "limit": limit}


@router.delete("/conversations/{conversation_id}")
async def delete_conversation(
    conversation_id: str,
    request: Request,
    user: UserIdentity = Depends(get_user_identity),
):
    ok = await request.app.state.history_store.delete_conversation(
        user.user_id, conversation_id
    )
    if not ok:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {"status": "deleted", "conversation_id": conversation_id}
