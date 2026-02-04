from __future__ import annotations

import logging
from qdrant_client import QdrantClient
from qdrant_client.http import models as qm

from .settings import settings

log = logging.getLogger(__name__)


def ensure_collection() -> None:
    client = QdrantClient(
        url=settings.qdrant_url, api_key=settings.qdrant_api_key, timeout=30
    )

    existing = {c.name for c in client.get_collections().collections}
    if settings.qdrant_collection in existing:
        return

    client.create_collection(
        collection_name=settings.qdrant_collection,
        vectors_config=qm.VectorParams(
            size=1536,  # text-embedding-3-small
            distance=qm.Distance.COSINE,
        ),
    )
    log.info(
        "qdrant_collection_created",
        extra={
            "request_id": "-",
            "user_id": "-",
            "collection": settings.qdrant_collection,
        },
    )
