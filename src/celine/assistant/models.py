from __future__ import annotations

from pydantic import BaseModel, Field
from typing import Literal


class SourceChunk(BaseModel):
    source: str = Field(..., description="Document source identifier")
    title: str | None = Field(default=None)
    text: str = Field(..., description="Snippet text")
    score: float | None = Field(default=None)


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1)
    conversation_id: str | None = Field(default=None)
    include_citations: bool = Field(default=True)
    top_k: int = Field(default=5, ge=1, le=20)


class ChatMeta(BaseModel):
    conversation_id: str


class SSEEvent(BaseModel):
    type: Literal["meta", "token", "sources", "done", "error"]
    data: str | list[SourceChunk] | ChatMeta | None = None


class HealthResponse(BaseModel):
    status: Literal["ok"]
