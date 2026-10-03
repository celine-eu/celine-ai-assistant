from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, cast

from llama_index.core import Document, StorageContext, VectorStoreIndex
from llama_index.core.retrievers import BaseRetriever
from llama_index.core.schema import BaseNode
from llama_index.core.vector_stores import (
    FilterCondition,
    FilterOperator,
    MetadataFilter,
    MetadataFilters,
)
from llama_index.vector_stores.qdrant import QdrantVectorStore
from qdrant_client import QdrantClient
from qdrant_client.http import models as qm

from celine.assistant import kb_collections, llm

log = logging.getLogger(__name__)

_index_lock = asyncio.Lock()
# One index per Qdrant name (an alias, or a generation being rebuilt).
_indexes: dict[str, VectorStoreIndex] = {}
_client: QdrantClient | None = None

# The kind written by the source ingester (`kb_sources.py`). It carries no `scope`: a
# source is the community's own reference material, readable by all its members.
CURATED_KINDS = ("kb_source",)


def qdrant() -> QdrantClient:
    global _client
    if _client is None:
        _client = kb_collections.qdrant_client()
    return _client


def _get_index(name: str) -> VectorStoreIndex:
    """The index over one Qdrant collection or alias, which must exist."""
    if name not in _indexes:
        vector_store = QdrantVectorStore(client=qdrant(), collection_name=name)
        _indexes[name] = VectorStoreIndex.from_vector_store(
            vector_store=vector_store,
            storage_context=StorageContext.from_defaults(vector_store=vector_store),
            embed_model=llm.embed_model(),
        )
    return _indexes[name]


def reset_indexes() -> None:
    """Forget cached indexes and client: the embedding settings or target changed."""
    global _client
    _indexes.clear()
    _client = None


def _read_target(community_id: str) -> str | None:
    """The community's alias when it exists. Reading never creates one."""
    alias = kb_collections.alias_name(community_id)
    if alias in _indexes or qdrant().collection_exists(alias):
        return alias
    return None


def _write_target(community_id: str) -> str:
    alias = kb_collections.alias_name(community_id)
    if alias not in _indexes:
        kb_collections.ensure_alias(qdrant(), community_id)
    return alias


def live_collection(community_id: str) -> str:
    """The generation the community's alias points at, creating both on first use."""
    alias = kb_collections.ensure_alias(qdrant(), community_id)
    return kb_collections.aliases(qdrant())[alias]


def visibility_filter(user_id: str | None, community_id: str) -> MetadataFilters:
    """What `user_id`, a member of `community_id`, may retrieve, as a vector-store filter.

    Each community has a collection of its own (`kb_collections.py`); inside it sit the
    community's sources, what its managers shared, and every member's own uploads. This
    is the rule that keeps the last of those apart, and the `community_id` term keeps a
    point that landed in the wrong collection out.
    """
    allowed: list[Any] = [
        MetadataFilter(key="scope", value="system", operator=FilterOperator.EQ),
        MetadataFilter(
            key="kind", value=list(CURATED_KINDS), operator=FilterOperator.IN
        ),
    ]
    if user_id:
        allowed.append(
            MetadataFilters(
                condition=FilterCondition.AND,
                filters=[
                    MetadataFilter(key="scope", value="user", operator=FilterOperator.EQ),
                    MetadataFilter(
                        key="owner_user_id", value=user_id, operator=FilterOperator.EQ
                    ),
                ],
            )
        )

    return MetadataFilters(
        condition=FilterCondition.AND,
        filters=[
            MetadataFilter(
                key="community_id", value=community_id, operator=FilterOperator.EQ
            ),
            MetadataFilters(condition=FilterCondition.OR, filters=allowed),
        ],
    )


def is_visible_to(
    metadata: dict[str, Any], user_id: str | None, community_id: str | None
) -> bool:
    """The same rule as `visibility_filter`, applied to a node we already have.

    Both exist on purpose. The filter is what makes the query efficient and is the real
    mechanism; it runs inside Qdrant. This one runs on every retrieved node and denies
    by default — so a filter that silently stops being applied costs results, not
    confidentiality.
    """
    if not community_id or metadata.get("community_id") != community_id:
        return False
    scope = metadata.get("scope")
    if scope == "system":
        return True
    if scope == "user":
        return bool(user_id) and metadata.get("owner_user_id") == user_id
    return metadata.get("kind") in CURATED_KINDS


def build_retriever(
    top_k: int = 5, *, user_id: str | None, community_id: str | None
) -> BaseRetriever | None:
    """None when there is nothing the caller may read: no community, or no knowledge
    base built for it yet.

    `user_id` and `community_id` are keyword-only with no default, so forgetting one is
    a TypeError rather than an unfiltered query.
    """
    if not community_id:
        return None
    try:
        target = _read_target(community_id)
    except kb_collections.InvalidCommunityId:
        log.error("kb_unusable_community_id", extra={"community": community_id})
        return None
    if target is None:
        return None
    return _get_index(target).as_retriever(
        similarity_top_k=top_k, filters=visibility_filter(user_id, community_id)
    )


def retrieve(
    retriever: BaseRetriever | None,
    query: str,
    top_k: int,
    *,
    user_id: str | None,
    community_id: str | None,
) -> List[BaseNode]:
    if retriever is None:
        return []
    try:
        setattr(retriever, "similarity_top_k", top_k)
    except Exception:
        pass
    nodes = retriever.retrieve(query)
    visible = [
        n
        for n in nodes
        if is_visible_to(getattr(n, "metadata", {}) or {}, user_id, community_id)
    ]
    if len(visible) != len(nodes):
        log.warning(
            "retrieval_filter_let_through_%d_hidden_nodes", len(nodes) - len(visible)
        )
    return cast(List[BaseNode], visible)


def attachment_doc_id(attachment_id: str) -> str:
    """The document id an uploaded attachment is indexed under.

    Deriving it rather than generating one is what makes the index entry deletable:
    `delete_document` needs a handle, and the attachment id is the only one both sides
    of that transaction share.
    """
    return f"attachment:{attachment_id}"


def _delete_ref_doc(name: str, doc_id: str) -> None:
    # The vector store rather than `index.delete_ref_doc`, which wants a docstore this
    # index does not have — it is built `from_vector_store`.
    _get_index(name).vector_store.delete(doc_id)


async def upsert_documents_from_text(
    *,
    community_id: str,
    text: str,
    metadata: dict[str, Any],
    doc_id: str | None = None,
    collection: str | None = None,
) -> dict[str, Any]:
    """Index one document into the community's knowledge base.

    `collection` names a generation being rebuilt instead of the live alias. With a
    `doc_id`, whatever was indexed under it before is replaced rather than duplicated.
    """
    if not text.strip():
        return {"inserted": 0}

    async with _index_lock:
        target = collection or await asyncio.to_thread(_write_target, community_id)
        doc = Document(text=text, metadata={**metadata, "community_id": community_id})
        if doc_id:
            doc.id_ = doc_id
            await asyncio.to_thread(_delete_ref_doc, target, doc_id)
        await asyncio.to_thread(_get_index(target).insert, doc)
        return {"inserted": 1}


async def delete_document(
    doc_id: str, *, community_id: str, collection: str | None = None
) -> None:
    """Remove every node derived from one document."""
    async with _index_lock:
        target = collection or await asyncio.to_thread(_read_target, community_id)
        if target is None:
            return
        await asyncio.to_thread(_delete_ref_doc, target, doc_id)


def count_points(name: str) -> int:
    return qdrant().count(name, exact=True).count


def indexed_values(name: str, key: str) -> set[str]:
    """Every distinct value of one payload field in a collection."""
    values: set[str] = set()
    offset = None
    while True:
        points, offset = qdrant().scroll(
            name, limit=256, offset=offset, with_payload=[key], with_vectors=False
        )
        for p in points:
            value = (p.payload or {}).get(key)
            if isinstance(value, str):
                values.add(value)
        if offset is None:
            return values


def delete_where(name: str, key: str, value: str) -> None:
    qdrant().delete(
        name,
        points_selector=qm.FilterSelector(
            filter=qm.Filter(
                must=[qm.FieldCondition(key=key, match=qm.MatchValue(value=value))]
            )
        ),
    )


def _node_text(node: BaseNode) -> str:
    get_content = getattr(node, "get_content", None)
    if callable(get_content):
        try:
            v = get_content()
            if isinstance(v, str):
                return v
        except Exception:
            pass

    text = getattr(node, "text", None)
    if isinstance(text, str):
        return text

    return str(node)


def node_to_source(node: BaseNode) -> Dict[str, Any]:
    meta = getattr(node, "metadata", {}) or {}
    score = getattr(node, "score", None)

    title = (
        meta.get("title")
        or meta.get("filename")
        or meta.get("source")
        or meta.get("source_uri")
    )
    source = (
        meta.get("source_uri")
        or meta.get("source")
        or meta.get("doc_id")
        or title
        or "unknown"
    )

    return {
        "source": source,
        "title": title,
        "text": _node_text(node),
        "score": score,
        "metadata": meta,
    }

