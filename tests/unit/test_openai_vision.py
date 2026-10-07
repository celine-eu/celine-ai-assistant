"""`openai_vision.describe_image`, against a faked chat client."""

from __future__ import annotations

from types import SimpleNamespace

from celine.assistant import openai_vision
from celine.assistant.settings import settings


class _FakeCompletions:
    def __init__(self):
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=" - a roof "))]
        )


# @verifies REQ-0051
async def test_an_image_caption_is_capped_and_uses_the_configured_sampling(monkeypatch):
    completions = _FakeCompletions()
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    monkeypatch.setattr(openai_vision, "_client", lambda: client)
    monkeypatch.setattr(settings, "llm_max_tokens", 900)
    monkeypatch.setattr(settings, "llm_temperature", None)

    out = await openai_vision.describe_image(
        image_bytes=b"\x89PNG", filename="roof.png"
    )

    assert out == "- a roof"
    assert completions.calls[0]["max_tokens"] == 900
    assert "temperature" not in completions.calls[0]
