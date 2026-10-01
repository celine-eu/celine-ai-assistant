from __future__ import annotations

import logging
from qdrant_client import QdrantClient
from qdrant_client.http import models as qm

from . import llm
from .settings import settings

log = logging.getLogger(__name__)


def collection_vector_size(info) -> int | None:
    """The vector size of an existing collection, if it has a single unnamed vector."""
    vectors = info.config.params.vectors
    return getattr(vectors, "size", None)


def ensure_collection(client: QdrantClient | None = None) -> None:
    """Create the collection at the embedding model's size, or refuse a mismatch.

    A collection built for one embedding model cannot be queried with another: Qdrant
    answers every search with a dimension error. Changing `LLM_EMBED_MODEL` therefore
    needs a new `QDRANT_COLLECTION` and a re-ingest, and this says so at startup.
    """
    client = client or QdrantClient(
        url=settings.qdrant_url, api_key=settings.qdrant_api_key, timeout=30
    )
    dimensions = llm.embedding_dimensions()

    existing = {c.name for c in client.get_collections().collections}
    if settings.qdrant_collection in existing:
        size = collection_vector_size(client.get_collection(settings.qdrant_collection))
        if size is not None and size != dimensions:
            raise RuntimeError(
                f"Qdrant collection {settings.qdrant_collection!r} holds {size}-dimension "
                f"vectors but {settings.llm_embed_model!r} produces {dimensions}. Set "
                "QDRANT_COLLECTION to a new collection and re-ingest."
            )
        return

    client.create_collection(
        collection_name=settings.qdrant_collection,
        vectors_config=qm.VectorParams(size=dimensions, distance=qm.Distance.COSINE),
    )
    log.info(
        "qdrant_collection_created",
        extra={
            "request_id": "-",
            "user_id": "-",
            "collection": settings.qdrant_collection,
        },
    )
