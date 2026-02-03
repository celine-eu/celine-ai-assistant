from __future__ import annotations

import logging
from typing import Any

from llama_index.core import Settings as LISettings
from llama_index.core.schema import NodeWithScore
from llama_index.core.retrievers import VectorIndexRetriever
from llama_index.core.indices.vector_store import VectorStoreIndex
from llama_index.vector_stores.qdrant import QdrantVectorStore
from llama_index.embeddings.openai import OpenAIEmbedding
from qdrant_client import QdrantClient

from .settings import settings

log = logging.getLogger(__name__)


def _qdrant_client() -> QdrantClient:
    return QdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key, timeout=30)


def build_retriever() -> VectorIndexRetriever:
    client = _qdrant_client()
    vector_store = QdrantVectorStore(client=client, collection_name=settings.qdrant_collection)

    embed_model = OpenAIEmbedding(model=settings.openai_embed_model, api_key=settings.openai_api_key)
    LISettings.embed_model = embed_model

    index = VectorStoreIndex.from_vector_store(vector_store=vector_store)
    return index.as_retriever(similarity_top_k=5)


def retrieve(retriever: VectorIndexRetriever, query: str, top_k: int) -> list[NodeWithScore]:
    retriever.similarity_top_k = top_k
    return retriever.retrieve(query)


def node_to_source(node: NodeWithScore) -> dict[str, Any]:
    md = node.node.metadata or {}
    src = md.get("source") or md.get("s3_key") or "unknown"
    title = md.get("title") or md.get("header_path")
    txt = node.node.get_text()
    snippet = txt[:1200]
    return {"source": src, "title": title, "text": snippet, "score": float(node.score or 0.0)}
