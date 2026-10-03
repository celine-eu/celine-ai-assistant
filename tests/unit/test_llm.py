"""`llm.py`. The collection check moved to `kb_collections.py`; see `test_kb_collections.py`.

The endpoint is configuration a deployment has to state; these tests hold the parts
that make an unstated or stale one fail at startup rather than send members' messages
somewhere nobody chose.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from celine.assistant import llm
from celine.assistant.settings import Settings, settings


@pytest.fixture(autouse=True)
def _no_leftovers(monkeypatch):
    """A developer's own `.env` may still carry the old names; these tests must not see it."""
    for name in ("OPENAI_API_KEY", "OPENAI_CHAT_MODEL", "OPENAI_EMBED_MODEL", "OPENAI_VISION_MODEL"):
        monkeypatch.delenv(name, raising=False)


def _cfg(**values) -> Settings:
    base = {
        "LLM_BASE_URL": "http://models.internal/v1",
        "LLM_CHAT_MODEL": "chat",
        "LLM_EMBED_MODEL": "embed",
    }
    base.update(values)
    return Settings(_env_file=None, **base)


# ── configuration_problems ────────────────────────────────────────


def test_a_complete_configuration_has_no_problems():
    assert llm.configuration_problems(_cfg()) == []


def test_no_endpoint_is_a_problem_not_a_vendor_default():
    problems = llm.configuration_problems(_cfg(LLM_BASE_URL=""))
    assert any("LLM_BASE_URL is not set" in p for p in problems)


@pytest.mark.parametrize("missing", ["LLM_CHAT_MODEL", "LLM_EMBED_MODEL"])
def test_each_model_must_be_named(missing):
    assert any(f"{missing} is not set" in p for p in llm.configuration_problems(_cfg(**{missing: ""})))


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("OPENAI_API_KEY", "LLM_API_KEY"),
        ("OPENAI_CHAT_MODEL", "LLM_CHAT_MODEL"),
        ("OPENAI_EMBED_MODEL", "LLM_EMBED_MODEL"),
        ("OPENAI_VISION_MODEL", "LLM_VISION_MODEL"),
    ],
)
def test_a_leftover_openai_variable_refuses_with_its_new_name(old, new):
    problems = llm.configuration_problems(_cfg(**{old: "x"}))
    assert any(old in p and new in p for p in problems), problems


# ── which endpoint and model each call uses ───────────────────────


def test_the_chat_client_uses_the_named_endpoint(monkeypatch):
    monkeypatch.setattr(settings, "llm_base_url", "http://models.internal/v1")
    monkeypatch.setattr(settings, "llm_api_key", "")
    client = llm.chat_client()
    assert str(client.base_url).rstrip("/") == "http://models.internal/v1"


def test_the_vision_model_defaults_to_the_chat_model(monkeypatch):
    monkeypatch.setattr(settings, "llm_chat_model", "multimodal")
    monkeypatch.setattr(settings, "llm_vision_model", "")
    assert llm.vision_model() == "multimodal"
    monkeypatch.setattr(settings, "llm_vision_model", "vision")
    assert llm.vision_model() == "vision"


def test_embeddings_use_their_own_endpoint_when_named(monkeypatch):
    monkeypatch.setattr(settings, "llm_base_url", "http://chat.internal/v1")
    monkeypatch.setattr(settings, "llm_api_key", "chat-key")
    monkeypatch.setattr(settings, "llm_embed_base_url", "")
    monkeypatch.setattr(settings, "llm_embed_api_key", "")
    assert llm._embed_endpoint() == ("http://chat.internal/v1", "chat-key")
    monkeypatch.setattr(settings, "llm_embed_base_url", "http://embed.internal/v1")
    assert llm._embed_endpoint() == ("http://embed.internal/v1", "not-used")


# ── EndpointEmbedding ─────────────────────────────────────────────


class _FakeEmbeddings:
    def __init__(self):
        self.calls: list[tuple[str, list[str]]] = []

    def create(self, *, model, input):
        self.calls.append((model, list(input)))
        # Returned out of order, as a server may: `index` is what ties a vector to its text.
        data = [SimpleNamespace(index=i, embedding=[float(i), float(len(t))]) for i, t in enumerate(input)]
        return SimpleNamespace(data=list(reversed(data)))


def test_endpoint_embedding_accepts_any_model_name_and_keeps_order():
    model = llm.EndpointEmbedding(model="any-open-model", base_url="http://e/v1", api_key="k")
    fake = _FakeEmbeddings()
    model._sync = SimpleNamespace(embeddings=fake)
    assert model.get_text_embedding_batch(["a", "bbb"]) == [[0.0, 1.0], [1.0, 3.0]]
    assert model.get_query_embedding("cc") == [0.0, 2.0]
    assert {m for m, _ in fake.calls} == {"any-open-model"}


def test_an_empty_dimension_setting_means_unset():
    """What a chart renders for a value it was not given."""
    assert _cfg(LLM_EMBED_DIMENSIONS="").llm_embed_dimensions is None
    assert _cfg(LLM_EMBED_DIMENSIONS="1024").llm_embed_dimensions == 1024


def test_the_dimensions_come_from_configuration_or_one_probe(monkeypatch):
    monkeypatch.setattr(settings, "llm_embed_dimensions", 1024)
    assert llm.embedding_dimensions() == 1024
    monkeypatch.setattr(settings, "llm_embed_dimensions", None)
    probe = SimpleNamespace(get_text_embedding=lambda text: [0.0] * 768)
    assert llm.embedding_dimensions(probe) == 768
