from __future__ import annotations

import asyncio
import json
import logging
from typing import AsyncGenerator

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse

from . import kb_sources
from .attachment_index import extract, index_attachment
from .auth import (
    UserIdentity,
    UserInfo,
    can_manage,
    community_id_of,
    extract_access_token,
    get_user_identity,
    is_admin,
)
from .kb_collections import InvalidCommunityId, validate_community_id
from .kb_store import KbStore
from .models import (
    ChatRequest,
    HealthResponse,
    KbSyncRequest,
)
from .rag import (
    attachment_doc_id,
    build_retriever,
    delete_document,
    node_to_source,
    retrieve,
)
from .history import HistoryStore, get_history_store
from .openai_stream import stream_chat
from .uploads import StoredFile, store_upload, open_upload_stream, delete_upload
from .settings import settings
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


def _may_read(att: dict, user: UserIdentity, community_id: str | None) -> bool:
    """A shared attachment is its community's; a member's own is theirs. A realm
    administrator reads either."""
    if is_admin(user):
        return True
    if att["scope"] == "system":
        return community_id is not None and att.get("community_id") == community_id
    if att["scope"] == "user":
        return att.get("owner_user_id") == user.user_id
    return False


async def _load_authorized_attachments(
    history_store: HistoryStore,
    user: UserIdentity,
    community_id: str | None,
    attachment_ids: list[str],
) -> list[dict]:
    out: list[dict] = []
    for att_id in attachment_ids:
        att = await history_store.get_attachment_any(att_id)
        if not att:
            continue
        if not _may_read(att, user, community_id):
            raise HTTPException(status_code=403, detail="Forbidden attachment access")
        out.append(att)
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


def _managed_community(user: UserIdentity, requested: str | None) -> str:
    """The community an administrator endpoint acts on, which the caller must manage.

    A REC manager acts on their own REC. A realm administrator has none of their own
    and names one.
    """
    community_id = requested or community_id_of(user)
    if not community_id:
        raise HTTPException(
            status_code=400, detail="Name the community (community_id) to act on"
        )
    try:
        validate_community_id(community_id)
    except InvalidCommunityId as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not can_manage(user, community_id):
        raise HTTPException(status_code=403, detail="Admin only")
    return community_id


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(status="ok")


@router.get("/ping")
async def ping(
    user: UserIdentity = Depends(get_user_identity),
) -> dict:
    return {"ok": True}


_UPLOAD_CHUNK_BYTES = 1024 * 1024


async def _read_upload_or_413(file: UploadFile) -> bytes:
    """Read the body in chunks and stop at the limit.

    Reading it whole and measuring afterwards would make the limit bound what is
    *stored* rather than what a caller can make this process allocate.
    """
    max_bytes = max(1, settings.max_upload_mb) * 1024 * 1024
    chunks: list[bytes] = []
    total = 0

    while chunk := await file.read(_UPLOAD_CHUNK_BYTES):
        total += len(chunk)
        if total > max_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"File too large (max {settings.max_upload_mb}MB)",
            )
        chunks.append(chunk)

    return b"".join(chunks)


async def _process_upload(
    history_store: HistoryStore,
    data: bytes,
    stored: StoredFile,
    scope: str,
    owner_user_id: str | None,
    community_id: str | None,
) -> dict:
    """Shared upload processing for both user and system scopes.

    Without a community the file is stored and can be attached to a turn, but there is
    no knowledge base to index it into.
    """
    extracted_text, caption = await extract(data, stored.filename, stored.content_type)

    att_id = await history_store.record_attachment(
        scope=scope,
        owner_user_id=owner_user_id,
        community_id=community_id,
        uri=stored.uri,
        path=stored.path,
        filename=stored.filename,
        content_type=stored.content_type,
        size_bytes=stored.size_bytes,
        caption=caption,
        ocr_text=extracted_text,
    )

    indexed = await index_attachment(
        {
            "id": att_id,
            "scope": scope,
            "owner_user_id": owner_user_id,
            "community_id": community_id,
            "uri": stored.uri,
            "filename": stored.filename,
            "content_type": stored.content_type,
            "caption": caption,
            "ocr_text": extracted_text,
        }
    )

    return {
        "status": "indexed" if indexed else "stored",
        "attachment_id": att_id,
        "uri": stored.uri,
        "filename": stored.filename,
        "content_type": stored.content_type,
        "size": stored.size_bytes,
        "scope": scope,
        "community_id": community_id,
        "caption": caption,
    }


@router.post("/upload")
async def upload_user(
    file: UploadFile = File(...),
    user: UserIdentity = Depends(get_user_identity),
    history_store: HistoryStore = Depends(get_history_store),
):
    community_id = community_id_of(user)
    data = await _read_upload_or_413(file)

    stored = await store_upload(
        scope="user",
        owner_user_id=user.user_id,
        filename=file.filename or "upload",
        content_type=file.content_type,
        data=data,
    )

    return await _process_upload(
        history_store=history_store,
        data=data,
        stored=stored,
        scope="user",
        owner_user_id=user.user_id,
        community_id=community_id,
    )


@router.post("/admin/uploads")
async def upload_system(
    file: UploadFile = File(...),
    community_id: str | None = Form(default=None),
    user: UserIdentity = Depends(get_user_identity),
    history_store: HistoryStore = Depends(get_history_store),
):
    target = _managed_community(user, community_id)
    data = await _read_upload_or_413(file)

    stored = await store_upload(
        scope="system",
        owner_user_id=None,
        filename=file.filename or "upload",
        content_type=file.content_type,
        data=data,
    )

    return await _process_upload(
        history_store=history_store,
        data=data,
        stored=stored,
        scope="system",
        owner_user_id=None,
        community_id=target,
    )


def get_kb_store() -> KbStore:
    return KbStore()


@router.post("/admin/kb/sync")
async def sync_knowledge_sources(
    req: KbSyncRequest,
    user: UserIdentity = Depends(get_user_identity),
    kb_store: KbStore = Depends(get_kb_store),
):
    """Sync the registered sources of one community's knowledge base."""
    target = _managed_community(user, req.community_id)
    results = await kb_sources.sync_all(
        kb_store=kb_store, community_id=target, full=req.full
    )
    return {"community_id": target, "sources": results}


@router.get("/attachments")
async def list_attachments(
    user: UserIdentity = Depends(get_user_identity),
    history_store: HistoryStore = Depends(get_history_store),
    limit: int = 200,
):
    items = await history_store.list_attachments_for_user(
        user.user_id, community_id_of(user), limit=limit
    )
    return {"items": items, "limit": limit}


async def _get_attachment_authorized(
    history_store: HistoryStore, user: UserIdentity, attachment_id: str
):
    att = await history_store.get_attachment_any(attachment_id)
    if not att:
        raise HTTPException(status_code=404, detail="Attachment not found")

    if att["scope"] not in ("system", "user"):
        raise HTTPException(status_code=500, detail="Invalid attachment scope")

    if not _may_read(att, user, community_id_of(user)):
        raise HTTPException(status_code=403, detail="Forbidden")
    return att


@router.get("/attachments/{attachment_id}/raw")
async def get_attachment_raw(
    attachment_id: str,
    user: UserIdentity = Depends(get_user_identity),
    history_store: HistoryStore = Depends(get_history_store),
):
    att = await _get_attachment_authorized(history_store, user, attachment_id)

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
    user: UserIdentity = Depends(get_user_identity),
    history_store: HistoryStore = Depends(get_history_store),
):
    att = await history_store.get_attachment_any(attachment_id)
    if not att:
        raise HTTPException(status_code=404, detail="Attachment not found")

    community_id = att.get("community_id")
    if att["scope"] == "system" and not (
        is_admin(user) or (community_id and can_manage(user, community_id))
    ):
        raise HTTPException(status_code=403, detail="Admin only")

    if (
        att["scope"] == "user"
        and (att.get("owner_user_id") != user.user_id)
        and not is_admin(user)
    ):
        raise HTTPException(status_code=403, detail="Forbidden")

    await history_store.delete_attachment_any(attachment_id)

    try:
        await delete_upload(att["path"])
    except Exception:
        log.exception("attachments_delete_blob_failed", extra={"path": att.get("path")})

    # The row and the blob are not the whole attachment: `_process_upload` also wrote it
    # into the vector store, and content left retrievable has not been deleted.
    try:
        if community_id:
            await delete_document(
                attachment_doc_id(attachment_id), community_id=community_id
            )
    except Exception:
        log.exception(
            "attachments_delete_index_failed", extra={"attachment": attachment_id}
        )

    return {"status": "deleted", "attachment_id": attachment_id}


@router.get("/user")
async def get_user(
    user: UserIdentity = Depends(get_user_identity),
) -> UserInfo:
    return UserInfo.from_identity(user)


@router.get("/suggestions")
async def suggestions(
    request: Request,
    user: UserIdentity = Depends(get_user_identity),
    history_store: HistoryStore = Depends(get_history_store),
    lang: str = "en",
):
    raw_token = extract_access_token(request)
    try:
        community_id = community_id_of(user)
    except HTTPException:
        community_id = None
    registry = build_skill_registry(
        user_token=raw_token,
        user_id=user.user_id,
        community_id=community_id,
        settings=settings,
        history_store=history_store,
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
    history_store: HistoryStore = Depends(get_history_store),
):
    user_message = req.message.strip()
    # Before anything is written: a token naming several RECs is refused outright.
    community_id = community_id_of(user)

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
        community_id=community_id,
        settings=settings,
        history_store=history_store,
    )

    attached = await _load_authorized_attachments(
        history_store, user, community_id, req.attachment_ids
    )
    attachment_block = _attachment_context_block(attached) if attached else None

    sources: list[dict] = []
    if user_message:
        retriever = await asyncio.to_thread(
            build_retriever,
            req.top_k,
            user_id=user.user_id,
            community_id=community_id,
        )
        nodes = await asyncio.to_thread(
            retrieve,
            retriever,
            user_message,
            req.top_k,
            user_id=user.user_id,
            community_id=community_id,
        )
        sources = [node_to_source(n) for n in nodes]
    public_sources = [source for source in sources if _is_public_source(source)]

    if attachment_block:
        sources = [attachment_block, *sources]
        public_sources = [attachment_block, *public_sources]

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
    user: UserIdentity = Depends(get_user_identity),
    history_store: HistoryStore = Depends(get_history_store),
    limit: int = 50,
    offset: int = 0,
):
    # Basic bounds to avoid accidental abuse
    limit = max(1, min(int(limit), 200))
    offset = max(0, int(offset))

    items = await history_store.list_conversations(
        user.user_id, limit=limit, offset=offset
    )
    return {"items": items, "limit": limit, "offset": offset}


@router.get("/conversations/{conversation_id}/messages")
async def conversation_messages(
    conversation_id: str,
    user: UserIdentity = Depends(get_user_identity),
    history_store: HistoryStore = Depends(get_history_store),
    limit: int = 200,
):
    limit = max(1, min(int(limit), 500))

    # Ownership is checked before the messages are read: an empty message list is
    # indistinguishable from a conversation that is not this caller's.
    if not await history_store.conversation_exists(user.user_id, conversation_id):
        raise HTTPException(status_code=404, detail="Conversation not found")

    messages = await history_store.list_messages(
        user.user_id, conversation_id, limit=limit
    )
    return {"messages": messages, "limit": limit}


@router.delete("/conversations/{conversation_id}")
async def delete_conversation(
    conversation_id: str,
    user: UserIdentity = Depends(get_user_identity),
    history_store: HistoryStore = Depends(get_history_store),
):
    ok = await history_store.delete_conversation(
        user.user_id, conversation_id
    )
    if not ok:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {"status": "deleted", "conversation_id": conversation_id}
