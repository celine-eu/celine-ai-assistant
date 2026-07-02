from __future__ import annotations

import json
import logging
from typing import Any

from .base import ProgressCallback, Skill

log = logging.getLogger(__name__)


class DocumentSkill(Skill):

    name = "documents"
    description = "Search and retrieve uploaded documents."

    def __init__(self, *, history_store: Any, user_id: str = "") -> None:
        self._history = history_store
        self._user_id = user_id

    def get_tools(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "search_documents",
                    "description": (
                        "Search the knowledge base for documents matching a query. "
                        "Returns relevant snippets from uploaded files, training materials, "
                        "and indexed documents."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "The search query.",
                            },
                            "top_k": {
                                "type": "integer",
                                "description": "Number of results to return. Default 5.",
                                "default": 5,
                            },
                        },
                        "required": ["query"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_attachment_info",
                    "description": (
                        "Get metadata and extracted text for a specific uploaded attachment "
                        "by its ID."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "attachment_id": {
                                "type": "string",
                                "description": "The attachment ID.",
                            },
                        },
                        "required": ["attachment_id"],
                    },
                },
            },
        ]

    async def execute(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        on_progress: ProgressCallback | None = None,
    ) -> str:
        try:
            if tool_name == "search_documents":
                return await self._search(
                    arguments["query"],
                    arguments.get("top_k", 5),
                    on_progress,
                )
            if tool_name == "get_attachment_info":
                return await self._get_attachment(
                    arguments["attachment_id"],
                    on_progress,
                )
        except Exception as exc:
            log.warning("doc_skill_failed", extra={"tool": tool_name, "error": str(exc)})
            return json.dumps({"error": str(exc)})

        return json.dumps({"error": f"Unknown tool: {tool_name}"})

    async def _search(
        self, query: str, top_k: int, on_progress: ProgressCallback | None
    ) -> str:
        import asyncio
        from celine.assistant.rag import build_retriever, retrieve, node_to_source

        if on_progress:
            await on_progress(f"Searching documents for: {query}")

        retriever = build_retriever(top_k)
        nodes = await asyncio.to_thread(retrieve, retriever, query, top_k)
        results = [node_to_source(n) for n in nodes]

        return json.dumps({
            "query": query,
            "results": [
                {
                    "source": r.get("source", ""),
                    "title": r.get("title", ""),
                    "text": r.get("text", "")[:2000],
                    "score": r.get("score"),
                }
                for r in results
            ],
        }, ensure_ascii=False)

    async def _get_attachment(
        self, attachment_id: str, on_progress: ProgressCallback | None
    ) -> str:
        if on_progress:
            await on_progress("Fetching attachment details...")

        att = await self._history.get_attachment_any(attachment_id)
        if not att:
            return json.dumps({"error": "Attachment not found."})

        if att["scope"] == "user" and att.get("owner_user_id") != self._user_id:
            return json.dumps({"error": "Attachment not found."})

        return json.dumps({
            "id": att.get("id"),
            "filename": att.get("filename"),
            "content_type": att.get("content_type"),
            "size_bytes": att.get("size_bytes"),
            "scope": att.get("scope"),
            "caption": att.get("caption"),
            "ocr_text": (att.get("ocr_text") or "")[:4000] or None,
            "created_at": att.get("created_at"),
        }, ensure_ascii=False, default=str)

    def get_system_prompt_fragment(self) -> str | None:
        return (
            "**Documents** (`search_documents`, `get_attachment_info`): "
            "Use `search_documents` to find relevant information in the knowledge base "
            "when the user asks questions that may be answered by uploaded documents or "
            "training materials. Use `get_attachment_info` to inspect a specific "
            "uploaded file's metadata and extracted text."
        )
