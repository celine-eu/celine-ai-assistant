from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import pathlib
from dataclasses import dataclass
from typing import Any

from llama_index.core import Document
from llama_index.core.node_parser import MarkdownNodeParser, SentenceSplitter
from llama_index.core.ingestion import IngestionPipeline
from llama_index.embeddings.openai import OpenAIEmbedding
from llama_index.vector_stores.qdrant import QdrantVectorStore
from qdrant_client import QdrantClient
from markitdown import MarkItDown

from .settings import settings
from .docs_source import list_objects, download_to_temp, ObjectInfo

log = logging.getLogger(__name__)

SUPPORTED_EXTS = {".doc", ".docx", ".pdf", ".md", ".txt"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff"}


@dataclass
class ManifestEntry:
    etag: str | None
    mtime: str | None
    size: int | None


class Manifest:
    def __init__(self, path: str):
        self.path = pathlib.Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._data: dict[str, dict[str, Any]] = {}
        self.load()

    def load(self) -> None:
        if self.path.exists():
            try:
                self._data = json.loads(self.path.read_text("utf-8"))
            except Exception:
                self._data = {}
        else:
            self._data = {}

    def save(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._data, indent=2, sort_keys=True), "utf-8")
        tmp.replace(self.path)

    def get(self, key: str) -> ManifestEntry | None:
        v = self._data.get(key)
        if not v:
            return None
        return ManifestEntry(
            etag=v.get("etag"), mtime=v.get("mtime"), size=v.get("size")
        )

    def set(self, key: str, obj: ObjectInfo) -> None:
        self._data[key] = {"etag": obj.etag, "mtime": obj.mtime, "size": obj.size}

    def clear(self) -> None:
        self._data = {}
        self.save()


def _qdrant_client() -> QdrantClient:
    return QdrantClient(
        url=settings.qdrant_url, api_key=settings.qdrant_api_key, timeout=30
    )


def _vector_store() -> QdrantVectorStore:
    client = _qdrant_client()
    return QdrantVectorStore(client=client, collection_name=settings.qdrant_collection)


def _node_parser():
    return MarkdownNodeParser()


def _fallback_node_parser():
    return SentenceSplitter(chunk_size=1024, chunk_overlap=150)


def _embedding_model():
    return OpenAIEmbedding(
        model=settings.openai_embed_model, api_key=settings.openai_api_key
    )


def _convert_to_markdown(file_path: str) -> tuple[str, dict[str, Any]]:
    ext = pathlib.Path(file_path).suffix.lower()

    if ext in {".md", ".txt"}:
        text = pathlib.Path(file_path).read_text("utf-8", errors="ignore")
        return text, {"converted_by": "raw"}

    converter = MarkItDown()
    res = converter.convert(file_path)
    md = getattr(res, "text_content", None) or str(res)
    meta = {"converted_by": "markitdown", "original_ext": ext}
    return md, meta


async def ingest_text_document(
    *,
    text: str,
    metadata: dict[str, Any],
) -> None:
    vector_store = _vector_store()
    embed_model = _embedding_model()

    pipeline = IngestionPipeline(
        transformations=[_node_parser(), embed_model],
        vector_store=vector_store,
    )

    doc = Document(text=text, metadata=metadata)

    try:
        await asyncio.to_thread(pipeline.run, documents=[doc])
    except Exception:
        fallback = IngestionPipeline(
            transformations=[_fallback_node_parser(), embed_model],
            vector_store=vector_store,
        )
        await asyncio.to_thread(fallback.run, documents=[doc])


async def ingest_file(
    *,
    local_path: str,
    source_uri: str,
    user_id: str,
    original_filename: str,
    content_type: str | None,
) -> None:
    ext = pathlib.Path(local_path).suffix.lower()

    if ext in IMAGE_EXTS or (content_type or "").startswith("image/"):
        from .openai_vision import describe_image

        with open(local_path, "rb") as f:
            img = f.read()
        desc = await describe_image(image_bytes=img, filename=original_filename)
        text = f"Image description for {original_filename}\n\n{desc}"
        meta = {
            "source": source_uri,
            "user_id": user_id,
            "kind": "image",
            "original_filename": original_filename,
            "content_type": content_type,
        }
        await ingest_text_document(text=text, metadata=meta)
        return

    md, conv_meta = _convert_to_markdown(local_path)
    meta = {
        "source": source_uri,
        "user_id": user_id,
        "kind": "document",
        "original_filename": original_filename,
        "content_type": content_type,
        **conv_meta,
    }
    await ingest_text_document(text=md, metadata=meta)


async def ingest_once(manifest: Manifest) -> dict[str, Any]:
    objs = await list_objects()

    to_process: list[ObjectInfo] = []
    skipped = 0

    for obj in objs:
        ext = pathlib.Path(obj.path).suffix.lower()
        if ext not in SUPPORTED_EXTS:
            continue
        prev = manifest.get(obj.path)
        if (
            prev
            and prev.etag == obj.etag
            and prev.mtime == obj.mtime
            and prev.size == obj.size
        ):
            skipped += 1
            continue
        to_process.append(obj)

    if not to_process:
        return {"processed": 0, "skipped": skipped, "total_seen": len(objs)}

    processed = 0
    errors: list[dict[str, Any]] = []

    for obj in to_process:
        try:
            local_path = await download_to_temp(obj.path)
            try:
                md, conv_meta = _convert_to_markdown(local_path)
                doc = Document(
                    text=md,
                    metadata={
                        "source": obj.uri,
                        "path": obj.path,
                        "etag": obj.etag,
                        "mtime": obj.mtime,
                        "size": obj.size,
                        "kind": "document",
                        **conv_meta,
                    },
                )
                vector_store = _vector_store()
                embed_model = _embedding_model()
                pipeline = IngestionPipeline(
                    transformations=[_node_parser(), embed_model],
                    vector_store=vector_store,
                )
                try:
                    await asyncio.to_thread(pipeline.run, documents=[doc])
                except Exception:
                    fallback = IngestionPipeline(
                        transformations=[_fallback_node_parser(), embed_model],
                        vector_store=vector_store,
                    )
                    await asyncio.to_thread(fallback.run, documents=[doc])
            finally:
                try:
                    os.remove(local_path)
                except Exception:
                    pass

            manifest.set(obj.path, obj)
            processed += 1

        except Exception as e:
            log.exception(
                "ingest_failed",
                extra={"request_id": "-", "user_id": "-", "s3_key": obj.path},
            )
            errors.append({"path": obj.path, "error": str(e)})

    manifest.save()
    return {
        "processed": processed,
        "skipped": skipped,
        "errors": errors,
        "total_seen": len(objs),
    }


class IngestService:
    def __init__(self) -> None:
        self._manifest = Manifest(settings.manifest_path)
        self._lock = asyncio.Lock()
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    async def start(self) -> None:
        if settings.ingest_force_reload_on_start:
            self._manifest.clear()

        if not settings.ingest_enable:
            log.info("ingest_disabled", extra={"request_id": "-", "user_id": "-"})
            return

        self._stop.clear()
        self._task = asyncio.create_task(self._run_loop())
        log.info("ingest_started", extra={"request_id": "-", "user_id": "-"})

    async def stop(self) -> None:
        if not self._task:
            return

        task = self._task
        self._task = None

        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    async def force_reload(self) -> dict[str, Any]:
        async with self._lock:
            self._manifest.clear()
            return await ingest_once(self._manifest)

    async def ingest_now(self) -> dict[str, Any]:
        async with self._lock:
            return await ingest_once(self._manifest)

    async def _run_loop(self) -> None:
        try:
            while True:
                try:
                    await self.ingest_now()
                except Exception as e:
                    log.exception(f"ingest_loop_error: {e}")
                await asyncio.sleep(max(5, settings.docs_poll_interval_seconds))
        except asyncio.CancelledError:
            raise
