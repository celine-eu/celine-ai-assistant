"""Starter prompts and tool labels — the only user-visible strings this service owns."""

from __future__ import annotations

from celine.assistant.skills.digital_twin import DigitalTwinSkill
from celine.assistant.skills.documents import DocumentSkill
from celine.assistant.skills.flexibility import FlexibilitySkill
from celine.assistant.skills.rec_registry import RecRegistrySkill
from celine.assistant.skills.weather import WeatherSkill
from celine.assistant.suggestions import (
    SUGGESTIONS,
    TOOL_LABELS,
    get_suggestions,
    get_tool_labels,
)

ALL_SKILLS = {"documents", "digital_twin", "weather", "rec_registry", "flexibility"}


# @verifies REQ-0029
def test_a_suggestion_is_translated():
    italian = get_suggestions(lang="it")
    assert "Quanta energia ho prodotto oggi?" in [s["text"] for s in italian]


# @verifies REQ-0029
def test_an_unknown_language_falls_back_to_english():
    assert get_suggestions(lang="de") == get_suggestions(lang="en")
    assert get_tool_labels(lang="de") == get_tool_labels(lang="en")


# @verifies REQ-0029
def test_suggestions_are_filtered_to_the_skills_that_are_available():
    only_weather = get_suggestions(available_skills={"weather"})

    assert only_weather
    assert len(only_weather) < len(get_suggestions())
    assert "cloud-sun" in [s["icon"] for s in only_weather]


# @verifies REQ-0029
def test_no_filter_means_every_suggestion():
    assert len(get_suggestions(available_skills=None)) == len(SUGGESTIONS)


def test_an_empty_availability_set_means_no_filter_rather_than_nothing_available():
    """`if available_skills and ...` treats the empty set as "do not filter".

    No caller can currently reach it — `build_skill_registry` always registers the
    documents skill, so the set is never empty — but the two readings are opposite and
    the code picks the surprising one.

    @verifies REQ-0029
    """
    assert len(get_suggestions(available_skills=set())) == len(SUGGESTIONS)


def test_every_suggestion_names_a_skill_that_exists():
    """A typo here does not fail: the suggestion silently never appears.

    @verifies REQ-0029
    """
    named = {s["skill"]["en"] for s in SUGGESTIONS}
    assert named <= ALL_SKILLS


def test_the_skill_names_are_the_registry_keys():
    """`/suggestions` filters on `registry.skills.keys()`, which are the `name`
    attributes — so these two vocabularies have to be the same one.

    @verifies REQ-0029
    """
    assert {
        DocumentSkill.name,
        DigitalTwinSkill.name,
        WeatherSkill.name,
        RecRegistrySkill.name,
        FlexibilitySkill.name,
    } == ALL_SKILLS


# @verifies REQ-0029
def test_every_suggestion_and_label_is_complete_in_every_language():
    languages = {"en", "it", "es"}
    for entry in SUGGESTIONS:
        assert set(entry["text"]) == languages
        assert set(entry["icon"]) == languages
    for labels in TOOL_LABELS.values():
        assert set(labels) == languages


def test_every_tool_the_skills_expose_has_a_label():
    """An unlabelled tool renders in the UI as a bare function name.

    @verifies REQ-0029
    """
    exposed = {
        tool["function"]["name"]
        for skill_cls, kwargs in (
            (DocumentSkill, {"history_store": None}),
            (DigitalTwinSkill, {"dt_base_url": "http://x", "user_token": "t", "user_id": "u"}),
            (WeatherSkill, {"dt_base_url": "http://x", "user_token": "t", "user_id": "u"}),
            (RecRegistrySkill, {"registry_base_url": "http://x", "user_token": "t"}),
            (
                FlexibilitySkill,
                {
                    "flexibility_base_url": "http://x",
                    "dt_base_url": "http://x",
                    "user_token": "t",
                    "user_id": "u",
                },
            ),
        )
        for tool in skill_cls(**kwargs).get_tools()
    }

    assert exposed <= set(TOOL_LABELS)
