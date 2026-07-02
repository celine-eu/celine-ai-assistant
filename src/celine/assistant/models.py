from __future__ import annotations

from pydantic import BaseModel, Field
from typing import Literal


class SourceChunk(BaseModel):
    source: str = Field(..., description="Document source identifier")
    title: str | None = Field(default=None)
    text: str = Field(..., description="Snippet text")
    score: float | None = Field(default=None)


class ChatRequest(BaseModel):
    message: str
    top_k: int = 5
    include_citations: bool = True
    conversation_id: str | None = None
    attachment_ids: list[str] = Field(default_factory=list)


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
