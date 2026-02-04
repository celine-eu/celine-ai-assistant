from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File
from fastapi.responses import StreamingResponse

from .auth import UserInfo, get_user_identity, UserIdentity
from .models import ChatRequest, HealthResponse
from .rag import build_retriever, retrieve, node_to_source
from .openai_stream import stream_chat
from .ingest import IngestService, ingest_file
from .uploads import store_upload
from .settings import settings

log = logging.getLogger(__name__)

router = APIRouter()
_retriever = build_retriever()


def _sse(event_type: str, data) -> str:
    payload = {"type": event_type, "data": data}
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(status="ok")


@router.post("/upload")
async def upload(
    request: Request,
    file: UploadFile = File(...),
    user: UserIdentity = Depends(get_user_identity),
):
    request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
    log_ctx = {"request_id": request_id, "user_id": user.user_id}

    try:
        data = await file.read()
        max_bytes = max(1, settings.max_upload_mb) * 1024 * 1024
        if len(data) > max_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"File too large (max {settings.max_upload_mb}MB)",
            )
    except HTTPException:
        raise
    except Exception as e:
        log.exception("upload_read_failed", extra=log_ctx)
        raise HTTPException(status_code=400, detail=str(e))

    try:
        stored = await store_upload(
            user_id=user.user_id,
            filename=file.filename or "upload",
            content_type=file.content_type,
            data=data,
        )
        log.info(
            "upload_stored",
            extra={**log_ctx, "uri": stored.uri, "size": stored.size_bytes},
        )

        # Ensure vector store has the textual meaning of the upload
        # For images: vision -> text description
        # For docs: markitdown -> markdown
        # Ingest expects a local path, so store_upload should be file:// for local,
        # but uploads could be s3://. For simplicity, for non-local uploads you can
        # mount the same S3 in DOCS_URI and rely on the poller, or extend uploads.py
        # to also download to temp then ingest. Here we support local uploads URI.
        if not stored.uri.startswith("file://"):
            return {
                "status": "stored",
                "uri": stored.uri,
                "note": "Upload stored in remote FS; ingestion by poller only (set DOCS_URI accordingly) or extend to temp-download.",
            }

        local_path = stored.uri[len("file://") :]
        await ingest_file(
            local_path=local_path,
            source_uri=stored.uri,
            user_id=user.user_id,
            original_filename=stored.filename,
            content_type=stored.content_type,
        )
        return {"status": "indexed", "uri": stored.uri, "filename": stored.filename}

    except HTTPException:
        raise
    except Exception as e:
        log.exception("upload_failed", extra=log_ctx)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/chat")
async def chat(
    req: ChatRequest,
    request: Request,
    user: UserIdentity = Depends(get_user_identity),
):
    request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
    log_ctx = {"request_id": request_id, "user_id": user.user_id}
    log.info("chat_request", extra=log_ctx)

    conv = await request.app.state.history_store.get_or_create_conversation(
        user.user_id, req.conversation_id
    )

    try:
        await request.app.state.history_store.append_message(
            user.user_id, conv.conversation_id, "user", req.message
        )
    except Exception:
        log.exception("history_append_user_failed", extra=log_ctx)

    try:
        nodes = await asyncio.to_thread(retrieve, _retriever, req.message, req.top_k)
        sources = [node_to_source(n) for n in nodes]
    except Exception as e:
        log.exception("retrieval_failed", extra=log_ctx)
        raise HTTPException(status_code=500, detail=f"Retrieval failed: {e}")

    async def gen() -> AsyncGenerator[str, None]:
        assistant_text_parts: list[str] = []
        try:
            yield _sse("meta", {"conversation_id": conv.conversation_id})

            if req.include_citations:
                yield _sse("sources", sources)

            async for tok in stream_chat(
                user_message=req.message, context_blocks=sources
            ):
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
                log.exception("history_append_assistant_failed", extra=log_ctx)

            yield _sse("done", None)
        except Exception as e:
            log.exception("chat_stream_failed", extra=log_ctx)
            yield _sse("error", str(e))

    return StreamingResponse(gen(), media_type="text/event-stream")


@router.get("/conversations/{conversation_id}/messages")
async def get_messages(
    conversation_id: str,
    request: Request,
    user: UserIdentity = Depends(get_user_identity),
):
    request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
    log_ctx = {"request_id": request_id, "user_id": user.user_id}
    try:
        msgs = await request.app.state.history_store.list_messages(
            user.user_id, conversation_id, limit=200
        )
        return {"conversation_id": conversation_id, "messages": msgs}
    except Exception as e:
        log.exception("history_list_failed", extra=log_ctx)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/user")
async def get_user(
    request: Request,
    user: UserIdentity = Depends(get_user_identity),
) -> UserInfo:
    info = UserInfo.from_identity(user)
    return info


@router.post("/admin/ingest")
async def admin_ingest_now(
    request: Request,
    user: UserIdentity = Depends(get_user_identity),
):
    svc: IngestService = request.app.state.ingest_service
    request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
    log_ctx = {"request_id": request_id, "user_id": user.user_id}

    try:
        result = await svc.ingest_now()
        log.info("ingest_now_ok", extra={**log_ctx, "result": result})
        return result
    except Exception as e:
        log.exception("ingest_now_failed", extra=log_ctx)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/admin/reload")
async def admin_force_reload(
    request: Request,
    user: UserIdentity = Depends(get_user_identity),
):
    svc: IngestService = request.app.state.ingest_service
    request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
    log_ctx = {"request_id": request_id, "user_id": user.user_id}

    try:
        result = await svc.force_reload()
        log.info("reload_ok", extra={**log_ctx, "result": result})
        return result
    except Exception as e:
        log.exception("reload_failed", extra=log_ctx)
        raise HTTPException(status_code=500, detail=str(e))
