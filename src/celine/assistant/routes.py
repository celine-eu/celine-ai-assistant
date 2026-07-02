from __future__ import annotations

import asyncio
import json
import logging
from typing import AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File
from fastapi.responses import StreamingResponse

from .auth import UserInfo, get_user_identity, UserIdentity, is_admin, extract_access_token
from .models import (
    ChatRequest,
    HealthResponse,
    TrainingMaterialsSyncRequest,
    page_context_block,
)
from .rag import build_retriever, retrieve, node_to_source
from .openai_stream import stream_chat
from .uploads import StoredFile, store_upload, open_upload_stream, delete_upload
from .settings import settings
from .openai_vision import describe_image
from .document_processing import detect_mime, extract_text
from .rag import upsert_documents_from_text
from .training_materials import sync_training_materials
from .skills.factory import build_skill_registry
from .suggestions import get_suggestions, get_tool_labels

log = logging.getLogger(__name__)

router = APIRouter()


def _sse(event_type: str, data) -> str:
    payload = json.dumps(data, ensure_ascii=False)
    return f"event: {event_type}\ndata: {payload}\n\n"


def _is_public_source(source: dict) -> bool:
    metadata = source.get("metadata") or {}
    return not bool(metadata.get("hidden"))


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


@router.get("/ping")
async def ping(
    user: UserIdentity = Depends(get_user_identity),
) -> dict:
    return {"ok": True}


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


async def _process_upload(
    request: Request,
    data: bytes,
    stored: StoredFile,
    scope: str,
    owner_user_id: str | None,
) -> dict:
    """Shared upload processing for both user and system scopes.

    Determines the processing path based on file type:
    - Images: describe via OpenAI vision
    - PDFs / documents: extract text via document_processing pipeline
    """
    detected_mime = detect_mime(data)
    effective_mime = (
        detected_mime
        if detected_mime != "application/octet-stream"
        else (stored.content_type or "")
    )

    extracted_text: str | None = None
    caption: str | None = None

    if _is_image(stored.filename, effective_mime):
        caption = await describe_image(image_bytes=data)
        extracted_text = caption
    elif effective_mime == "application/pdf" or stored.filename.lower().endswith(".pdf"):
        extracted_text = await extract_text(data, effective_mime, stored.filename)
    else:
        try:
            extracted_text = await extract_text(data, effective_mime, stored.filename)
        except Exception:
            log.warning("extract_text_failed", extra={"filename": stored.filename})

    att_id = await request.app.state.history_store.record_attachment(
        scope=scope,
        owner_user_id=owner_user_id,
        uri=stored.uri,
        path=stored.path,
        filename=stored.filename,
        content_type=stored.content_type,
        size_bytes=stored.size_bytes,
        caption=caption,
        ocr_text=extracted_text,
    )

    if extracted_text:
        kind = "image_caption" if caption else "document_content"
        label = (
            f"Image description for {stored.filename}"
            if caption
            else f"Document content for {stored.filename}"
        )
        await upsert_documents_from_text(
            text=f"{label}:\n{extracted_text}",
            metadata={
                "attachment_id": att_id,
                "source_uri": stored.uri,
                "filename": stored.filename,
                "content_type": stored.content_type,
                "scope": scope,
                "owner_user_id": owner_user_id,
                "kind": kind,
            },
        )

    return {
        "status": "indexed" if extracted_text else "stored",
        "attachment_id": att_id,
        "uri": stored.uri,
        "filename": stored.filename,
        "content_type": stored.content_type,
        "size": stored.size_bytes,
        "scope": scope,
        "caption": caption,
    }


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

    return await _process_upload(
        request=request,
        data=data,
        stored=stored,
        scope="user",
        owner_user_id=user.user_id,
    )


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

    return await _process_upload(
        request=request,
        data=data,
        stored=stored,
        scope="system",
        owner_user_id=None,
    )


@router.post("/admin/training-materials/sync")
async def sync_training_materials_route(
    req: TrainingMaterialsSyncRequest,
    admin: UserIdentity = Depends(require_admin),
):
    _ = admin
    try:
        return await sync_training_materials(
            target_ref=req.target_ref, force_full=False
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


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


@router.get("/suggestions")
async def suggestions(
    request: Request,
    user: UserIdentity = Depends(get_user_identity),
    lang: str = "en",
):
    raw_token = extract_access_token(request)
    registry = build_skill_registry(
        user_token=raw_token,
        user_id=user.user_id,
        settings=settings,
        history_store=request.app.state.history_store,
    )
    available = set(registry.skills.keys())
    return {
        "suggestions": get_suggestions(lang=lang, available_skills=available),
        "tool_labels": get_tool_labels(lang=lang),
    }


@router.post("/chat")
async def chat(
    req: ChatRequest,
    request: Request,
    user: UserIdentity = Depends(get_user_identity),
):
    user_message = req.message.strip()
    history_store = request.app.state.history_store

    conv = await history_store.get_or_create_conversation(
        user.user_id, req.conversation_id
    )

    try:
        await history_store.append_message(
            user.user_id, conv.conversation_id, "user", req.message
        )
    except Exception:
        log.exception("history_append_user_failed")

    raw_token = extract_access_token(request)
    skill_registry = build_skill_registry(
        user_token=raw_token,
        user_id=user.user_id,
        settings=settings,
        history_store=history_store,
    )

    attached = await _load_authorized_attachments(request, user, req.attachment_ids)
    attachment_block = _attachment_context_block(attached) if attached else None
    page_block = page_context_block(req.context)

    sources: list[dict] = []
    if user_message:
        retriever = build_retriever(req.top_k)
        nodes = await asyncio.to_thread(retrieve, retriever, user_message, req.top_k)
        sources = [node_to_source(n) for n in nodes]
    public_sources = [source for source in sources if _is_public_source(source)]

    if attachment_block:
        sources = [attachment_block, *sources]
        public_sources = [attachment_block, *public_sources]

    if page_block:
        sources = [page_block, *sources]

    effective_message = (
        user_message
        or "Analyze the attached files and provide a concise summary of the relevant information."
    )

    history_messages = await history_store.list_messages(
        user.user_id, conv.conversation_id, limit=settings.chat_history_limit
    )
    prior_messages = [
        {"role": m["role"], "content": m["content"]}
        for m in history_messages
        if m["role"] in ("user", "assistant") and m["content"]
    ]
    if prior_messages and prior_messages[-1].get("role") == "user":
        prior_messages = prior_messages[:-1]

    async def gen() -> AsyncGenerator[str, None]:
        assistant_text_parts: list[str] = []
        yield _sse("meta", {"conversation_id": conv.conversation_id})
        if req.include_citations:
            yield _sse("sources", public_sources)

        async for event_str in stream_chat(
            user_message=effective_message,
            context_blocks=sources,
            history=prior_messages,
            skill_registry=skill_registry,
        ):
            if event_str.startswith("event: token\n"):
                data_line = event_str.split("data: ", 1)[1].rstrip("\n")
                try:
                    tok = json.loads(data_line)
                    if isinstance(tok, str):
                        assistant_text_parts.append(tok)
                except (json.JSONDecodeError, TypeError):
                    pass
            yield event_str

        try:
            full_text = "".join(assistant_text_parts)
            if full_text:
                await history_store.append_message(
                    user.user_id,
                    conv.conversation_id,
                    "assistant",
                    full_text,
                )
        except Exception:
            log.exception("history_append_assistant_failed")

        yield _sse("done", None)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


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
