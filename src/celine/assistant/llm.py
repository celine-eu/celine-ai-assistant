"""Where the language models are: the one place that builds a model client.

Chat, history summaries, image captions and embeddings all go to OpenAI-compatible
endpoints the deployment names (`LLM_BASE_URL`, optionally `LLM_EMBED_BASE_URL`). What
crosses them is a member's messages and the data the tools fetch with the member's own
token, so the endpoint is configuration that has to be stated, never a default.
"""

from __future__ import annotations

from typing import Any

from llama_index.core.base.embeddings.base import BaseEmbedding
from openai import AsyncOpenAI, OpenAI
from pydantic import PrivateAttr

from .settings import Settings, settings

# What each removed variable is called now.
_RENAMED = {
    "removed_openai_api_key": ("OPENAI_API_KEY", "LLM_API_KEY"),
    "removed_openai_chat_model": ("OPENAI_CHAT_MODEL", "LLM_CHAT_MODEL"),
    "removed_openai_embed_model": ("OPENAI_EMBED_MODEL", "LLM_EMBED_MODEL"),
    "removed_openai_vision_model": ("OPENAI_VISION_MODEL", "LLM_VISION_MODEL"),
}


def configuration_problems(cfg: Settings) -> list[str]:
    """Why the model configuration cannot be used, or nothing. Checked at startup."""
    problems = [
        f"{old} is no longer read; set {new} (and LLM_BASE_URL) instead"
        for field, (old, new) in _RENAMED.items()
        if getattr(cfg, field)
    ]
    if not cfg.llm_base_url:
        problems.append(
            "LLM_BASE_URL is not set: name the OpenAI-compatible endpoint the assistant "
            "sends members' messages to"
        )
    if not cfg.llm_chat_model:
        problems.append("LLM_CHAT_MODEL is not set")
    if not cfg.llm_embed_model:
        problems.append("LLM_EMBED_MODEL is not set")
    return problems


def _api_key(value: str) -> str:
    # The client refuses an empty key; a self-hosted server usually wants none.
    return value or "not-used"


def chat_client() -> AsyncOpenAI:
    return AsyncOpenAI(base_url=settings.llm_base_url, api_key=_api_key(settings.llm_api_key))


def vision_model() -> str:
    return settings.llm_vision_model or settings.llm_chat_model


def _embed_endpoint() -> tuple[str, str]:
    if settings.llm_embed_base_url:
        return settings.llm_embed_base_url, _api_key(settings.llm_embed_api_key)
    return settings.llm_base_url, _api_key(settings.llm_embed_api_key or settings.llm_api_key)


class EndpointEmbedding(BaseEmbedding):
    """LlamaIndex embeddings from any OpenAI-compatible `/embeddings` endpoint.

    `llama_index.embeddings.openai.OpenAIEmbedding` refuses a model name that is not one
    of OpenAI's own, so it cannot talk to a self-hosted model.
    """

    _sync: Any = PrivateAttr()
    _async: Any = PrivateAttr()

    def __init__(self, *, model: str, base_url: str, api_key: str, **kwargs: Any) -> None:
        super().__init__(model_name=model, **kwargs)
        self._sync = OpenAI(base_url=base_url, api_key=api_key)
        self._async = AsyncOpenAI(base_url=base_url, api_key=api_key)

    @classmethod
    def class_name(cls) -> str:
        return "EndpointEmbedding"

    def _get_text_embeddings(self, texts: list[str]) -> list[list[float]]:
        resp = self._sync.embeddings.create(model=self.model_name, input=texts)
        return [item.embedding for item in sorted(resp.data, key=lambda d: d.index)]

    async def _aget_text_embeddings(self, texts: list[str]) -> list[list[float]]:
        resp = await self._async.embeddings.create(model=self.model_name, input=texts)
        return [item.embedding for item in sorted(resp.data, key=lambda d: d.index)]

    def _get_text_embedding(self, text: str) -> list[float]:
        return self._get_text_embeddings([text])[0]

    async def _aget_text_embedding(self, text: str) -> list[float]:
        return (await self._aget_text_embeddings([text]))[0]

    def _get_query_embedding(self, query: str) -> list[float]:
        return self._get_text_embedding(query)

    async def _aget_query_embedding(self, query: str) -> list[float]:
        return await self._aget_text_embedding(query)


def embed_model() -> EndpointEmbedding:
    base_url, api_key = _embed_endpoint()
    return EndpointEmbedding(model=settings.llm_embed_model, base_url=base_url, api_key=api_key)


def embedding_dimensions(model: BaseEmbedding | None = None) -> int:
    """The configured vector size, or the size of one embedding when none is set."""
    if settings.llm_embed_dimensions:
        return settings.llm_embed_dimensions
    return len((model or embed_model()).get_text_embedding("dimension probe"))
