"""Which skills the model is offered, and on what.

The registry is rebuilt per request from the caller's own token — the assistant is a
BFF and forwards the user's identity downstream rather than holding a service account.
That is why a missing token silently removes capabilities instead of failing the request.
"""

from __future__ import annotations

import pytest

from celine.assistant.settings import settings as real_settings
from celine.assistant.skills.factory import build_skill_registry


def settings_with(**overrides):
    return real_settings.model_copy(update=overrides)


ALL_URLS = {
    "digital_twin_api_url": "http://dt.test",
    "rec_registry_api_url": "http://rec.test",
    "flexibility_api_url": "http://flex.test",
}


def build(token: str | None, **overrides):
    return build_skill_registry(
        user_token=token,
        user_id="alice",
        settings=settings_with(**{**ALL_URLS, **overrides}),
        history_store=object(),
    )


# @verifies REQ-0027
def test_a_token_and_every_url_offers_every_skill():
    assert set(build("tok").skills) == {
        "documents",
        "digital_twin",
        "weather",
        "rec_registry",
        "flexibility",
    }


def test_without_a_token_only_the_local_skill_survives():
    """Documents needs no upstream — it reads Qdrant and this service's own database.

    @verifies REQ-0027
    """
    assert set(build(None).skills) == {"documents"}


# @verifies REQ-0027
def test_an_unconfigured_upstream_removes_its_skills():
    assert "rec_registry" not in build("tok", rec_registry_api_url=None).skills


def test_the_digital_twin_url_carries_the_weather_skill_too():
    """Weather is served by the digital twin's fetchers, not by a weather service.

    @verifies REQ-0027
    """
    skills = build("tok", digital_twin_api_url=None).skills
    assert "digital_twin" not in skills
    assert "weather" not in skills


def test_flexibility_needs_the_digital_twin_as_well_as_its_own_url():
    """It resolves the user's device through the twin before it can score anything.

    @verifies REQ-0027
    """
    assert "flexibility" not in build("tok", digital_twin_api_url=None).skills
    assert "flexibility" not in build("tok", flexibility_api_url=None).skills


def test_the_dataset_skill_is_not_offered():
    """`dataset-api` wants a service token and this service only has the user's.
    Re-enabling it is a token-exchange problem, not a registration one.

    @verifies REQ-0027
    """
    assert "datasets" not in build("tok").skills


@pytest.mark.parametrize("token", ["", None])
# @verifies REQ-0027
def test_an_empty_token_counts_as_no_token(token):
    assert set(build(token).skills) == {"documents"}
