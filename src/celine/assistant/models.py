from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field
from typing import Literal


class SourceChunk(BaseModel):
    source: str = Field(..., description="Document source identifier")
    title: str | None = Field(default=None)
    text: str = Field(..., description="Snippet text")
    score: float | None = Field(default=None)


class ChatContext(BaseModel):
    page: str | None = None
    section: str | None = None
    data: dict[str, Any] | None = None
    hint: str | None = None


class ChatRequest(BaseModel):
    message: str
    top_k: int = 5
    include_citations: bool = True
    conversation_id: str | None = None
    attachment_ids: list[str] = Field(default_factory=list)
    context: ChatContext | None = None


def page_context_block(context: ChatContext | None) -> dict | None:
    if context is None:
        return None

    page = (context.page or "").strip()
    section = (context.section or "").strip()
    if not page and not section:
        return None

    page_lower = page.lower()
    lines = [
        "The user is interacting with a specific application page.",
    ]

    if page:
        lines.append(f"- current_page: {page}")
    if section:
        lines.append(f"- current_section: {section}")
    if context.hint:
        lines.append(f"- user_intent_hint: {context.hint}")

    if page_lower in {"panoramica", "overview", "dashboard", "home"}:
        lines.extend(
            [
                "Page semantics:",
                "- 'Panoramica' is the dashboard overview page.",
                "- On this page, the most relevant values are the user's production, consumption, self-consumption, self-consumption rate, and the REC-level aggregates/trend.",
                "- If the user asks 'these values', 'this page', or 'panoramica', interpret the question as referring to the overview dashboard.",
            ]
        )

    if context.data:
        lines.extend(
            [
                "Structured page data:",
                str(context.data),
            ]
        )

    return {
        "source": "page_context",
        "title": "Current page context",
        "text": "\n".join(lines),
        "score": 1.0,
        "metadata": {"kind": "page_context", "hidden": True, "page": page, "section": section},
    }


class ChatMeta(BaseModel):
    conversation_id: str


class SSEEvent(BaseModel):
    type: Literal[
        "meta", "token", "sources", "done", "error",
        "tool_start", "tool_progress", "tool_result", "tool_error",
    ]
    data: str | list[SourceChunk] | ChatMeta | None = None


class HealthResponse(BaseModel):
    status: str = "ok"


class TrainingMaterialsSyncRequest(BaseModel):
    target_ref: str | None = Field(
        default=None, description="Git commit SHA, tag, or ref to sync"
    )
