from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Dict, List, Optional, cast

from llama_index.core import Document, Settings, StorageContext, VectorStoreIndex
from llama_index.core.readers import SimpleDirectoryReader
from llama_index.core.retrievers import BaseRetriever
from llama_index.core.schema import BaseNode
from llama_index.core.vector_stores import (
    FilterCondition,
    FilterOperator,
    MetadataFilter,
    MetadataFilters,
)
from llama_index.embeddings.openai import OpenAIEmbedding
from llama_index.vector_stores.qdrant import QdrantVectorStore
from qdrant_client import QdrantClient

from celine.assistant.settings import settings

log = logging.getLogger(__name__)

_index_lock = asyncio.Lock()
_index: Optional[VectorStoreIndex] = None

# The kinds written by the corpus ingesters. These carry no `scope`, and they are
# readable by every member by design — that is what the curated corpus is.
CURATED_KINDS = ("training_material", "site_doc")


def _get_index() -> VectorStoreIndex:
    global _index

    if _index is None:
        if not settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY missing")

        os.environ.setdefault("OPENAI_API_KEY", settings.openai_api_key)

        Settings.embed_model = OpenAIEmbedding(model=settings.openai_embed_model)
        client = QdrantClient(
            url=settings.qdrant_url, api_key=settings.qdrant_api_key, timeout=30
        )
        vector_store = QdrantVectorStore(
            client=client,
            collection_name=settings.qdrant_collection,
        )
        storage_context = StorageContext.from_defaults(vector_store=vector_store)
        _index = VectorStoreIndex.from_vector_store(
            vector_store=vector_store,
            storage_context=storage_context,
        )

    return _index


def visibility_filter(user_id: str | None) -> MetadataFilters:
    """What `user_id` is allowed to retrieve, as a vector-store filter.

    One shared collection holds the curated corpus, administrator-shared files and every
    member's own uploads (`.agents/knowledge/rag-corpus-isolation.md`). This is the rule
    that keeps the last of those apart.
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

    return MetadataFilters(condition=FilterCondition.OR, filters=allowed)


def is_visible_to(metadata: dict[str, Any], user_id: str | None) -> bool:
    """The same rule as `visibility_filter`, applied to a node we already have.

    Both exist on purpose. The filter is what makes the query efficient and is the real
    mechanism; it runs inside Qdrant, so no test that does not start Qdrant can prove it
    works. This one is checkable, runs on every retrieved node, and denies by default —
    so a filter that silently stops being applied costs results, not confidentiality.
    """
    scope = metadata.get("scope")
    if scope == "system":
        return True
    if scope == "user":
        return bool(user_id) and metadata.get("owner_user_id") == user_id
    return metadata.get("kind") in CURATED_KINDS


def build_retriever(top_k: int = 5, *, user_id: str | None) -> BaseRetriever:
    """`user_id` is keyword-only and has no default, so forgetting it is a TypeError
    rather than an unfiltered query.
    """
    idx = _get_index()
    return idx.as_retriever(
        similarity_top_k=top_k, filters=visibility_filter(user_id)
    )


def retrieve(
    retriever: BaseRetriever, query: str, top_k: int, *, user_id: str | None
) -> List[BaseNode]:
    try:
        setattr(retriever, "similarity_top_k", top_k)
    except Exception:
        pass
    nodes = retriever.retrieve(query)
    visible = [
        n for n in nodes if is_visible_to(getattr(n, "metadata", {}) or {}, user_id)
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


async def upsert_documents_from_text(
    *, text: str, metadata: dict[str, Any], doc_id: str | None = None
) -> dict[str, Any]:
    if not text.strip():
        return {"inserted": 0}

    async with _index_lock:
        idx = _get_index()
        doc = Document(text=text, metadata=dict(metadata))
        if doc_id:
            doc.id_ = doc_id
        _insert_into_index(idx, [doc])
        return {"inserted": 1}


async def delete_document(doc_id: str) -> None:
    """Remove every node derived from one document.

    Goes to the vector store rather than `index.delete_ref_doc`, which wants a docstore
    this index does not have — it is built `from_vector_store`.

    Documents indexed before document ids were derived (2026-08-15) carry generated ones
    and are not reachable this way; clearing those needs a reindex.
    """
    async with _index_lock:
        idx = _get_index()
        await asyncio.to_thread(idx.vector_store.delete, doc_id)


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


def _insert_into_index(index: VectorStoreIndex, docs: list[Document]) -> None:
    ix: Any = index

    fn = getattr(ix, "insert_documents", None)
    if callable(fn):
        fn(docs)
        return

    fn = getattr(ix, "add_documents", None)
    if callable(fn):
        fn(docs)
        return

    fn = getattr(ix, "insert", None)
    if callable(fn):
        for d in docs:
            fn(d)
        return

    raise RuntimeError(
        "VectorStoreIndex has no supported insert method (insert_documents/add_documents/insert)"
    )


async def upsert_documents_from_file(
    *, local_path: str, metadata: Dict[str, Any]
) -> Dict[str, Any]:
    if not os.path.exists(local_path):
        raise FileNotFoundError(local_path)

    async with _index_lock:
        idx = _get_index()
        docs = await asyncio.to_thread(_read_file_as_documents, local_path, metadata)
        if not docs:
            return {"inserted": 0}

        _insert_into_index(idx, docs)
        return {"inserted": len(docs)}


def _read_file_as_documents(path: str, metadata: Dict[str, Any]) -> List[Document]:
    reader = SimpleDirectoryReader(input_files=[path])
    loaded = reader.load_data()

    out: List[Document] = []
    for d in loaded:
        base_meta = dict(getattr(d, "metadata", {}) or {})
        base_meta.update(metadata)
        out.append(Document(text=d.text, metadata=base_meta))
    return out
