"""What produced an answer, kept beside it so a disputed answer can be investigated.

REQ-0053. The route opens an `AnswerTrace` with what it gives the model (context
blocks, attachments); the agentic loop adds what only it sees (the model the endpoint
reports, each tool call); the route stores `to_dict()` on the `assistant` row. Never the
text of a source and never a tool's result: identifiers and arguments only.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from importlib import metadata
from typing import Any

from .settings import settings

# The metadata keys that name where a context block came from. The rest of the metadata
# (owner, community, title, location) is either the caller's own or readable from the
# source it names.
_SOURCE_ID_KEYS = ("kind", "doc_id", "source_id", "attachment_id")


def _service_version() -> str | None:
    try:
        return metadata.version("celine-chatbot-api")
    except metadata.PackageNotFoundError:
        return None


SERVICE_VERSION = _service_version()


def source_ref(block: dict[str, Any]) -> dict[str, Any]:
    """One context block as the trace keeps it: what it was, not what it said."""
    meta = block.get("metadata") or {}
    ref: dict[str, Any] = {"source": block.get("source"), "score": block.get("score")}
    for key in _SOURCE_ID_KEYS:
        if meta.get(key) is not None:
            ref[key] = meta[key]
    return ref


@dataclass
class AnswerTrace:
    """The trace of one answer: filled during the turn, stored with the answer."""

    requested_model: str
    service_version: str | None
    attachments: list[str]
    sources: list[dict[str, Any]]
    tools: list[dict[str, Any]] = field(default_factory=list)
    reported_model: str | None = None
    fingerprint: str | None = None

    @classmethod
    def for_turn(
        cls, *, context_blocks: list[dict[str, Any]], attachment_ids: list[str]
    ) -> AnswerTrace:
        """A trace for a turn about to be answered from these blocks and attachments."""
        return cls(
            requested_model=settings.llm_chat_model,
            service_version=SERVICE_VERSION,
            attachments=list(attachment_ids),
            sources=[source_ref(b) for b in context_blocks],
        )

    def saw_chunk(self, chunk: Any) -> None:
        """Note the model the endpoint says produced this streamed chunk, if it says."""
        model = getattr(chunk, "model", None)
        if isinstance(model, str) and model:
            self.reported_model = model
        fingerprint = getattr(chunk, "system_fingerprint", None)
        if isinstance(fingerprint, str) and fingerprint:
            self.fingerprint = fingerprint

    def tool_called(self, name: str, raw_arguments: str) -> dict[str, Any]:
        """Record a tool call and return its entry, so the caller can mark it failed.

        The arguments are kept parsed when they are JSON and as sent when they are not:
        a malformed call is exactly what an investigation wants to see.
        """
        try:
            arguments: Any = json.loads(raw_arguments)
        except (json.JSONDecodeError, TypeError):
            arguments = raw_arguments
        entry: dict[str, Any] = {"name": name, "arguments": arguments}
        self.tools.append(entry)
        return entry

    def to_dict(self) -> dict[str, Any]:
        """The JSON stored in `messages.trace`."""
        return {
            "model": {
                "requested": self.requested_model,
                "reported": self.reported_model,
                "fingerprint": self.fingerprint,
            },
            "service_version": self.service_version,
            "attachments": list(self.attachments),
            "sources": [dict(s) for s in self.sources],
            "tools": [dict(t) for t in self.tools],
        }
