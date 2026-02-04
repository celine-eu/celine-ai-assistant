from __future__ import annotations

import asyncio
import os
from typing import Any, Dict, List, Optional, cast

from llama_index.core import Document, VectorStoreIndex
from llama_index.core.readers import SimpleDirectoryReader
from llama_index.core.retrievers import BaseRetriever
from llama_index.core.schema import BaseNode

_index_lock = asyncio.Lock()
_index: Optional[VectorStoreIndex] = None


def _get_index() -> VectorStoreIndex:
    global _index
    if _index is None:
        _index = VectorStoreIndex.from_documents([])
    return _index


def build_retriever(top_k: int = 5) -> BaseRetriever:
    idx = _get_index()
    return idx.as_retriever(similarity_top_k=top_k)


def retrieve(retriever: BaseRetriever, query: str, top_k: int) -> List[BaseNode]:
    try:
        setattr(retriever, "similarity_top_k", top_k)
    except Exception:
        pass
    nodes = retriever.retrieve(query)
    return cast(List[BaseNode], nodes)


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

    for method in ("insert_documents", "insert", "add_documents"):
        fn = getattr(ix, method, None)
        if callable(fn):
            fn(docs)
            return

    raise RuntimeError(
        "VectorStoreIndex has no supported insert method (insert_documents/insert/add_documents)"
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
