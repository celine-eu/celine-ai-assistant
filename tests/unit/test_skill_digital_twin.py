"""How the digital-twin skill reads energy data, and what it reports when it cannot."""

from __future__ import annotations

import json

import pytest

from celine.assistant.skills import digital_twin as dt_module
from celine.assistant.skills.digital_twin import DigitalTwinSkill
from tests.fakes import (
    FakeCommunities,
    FakeDTClient,
    FakeParticipants,
    Item,
    Page,
    install_dt,
    member_of,
    with_sensors,
)


def build(monkeypatch, client: FakeDTClient) -> DigitalTwinSkill:
    install_dt(monkeypatch, dt_module, client)
    return DigitalTwinSkill(dt_base_url="http://dt.test", user_token="tok", user_id="alice")


async def run(skill: DigitalTwinSkill, tool: str, **args) -> dict:
    return json.loads(await skill.execute(tool, args))


# --- profile ----------------------------------------------------------------


# @verifies REQ-0027
async def test_a_profile_reports_the_community(monkeypatch):
    skill = build(
        monkeypatch,
        FakeDTClient(participants=FakeParticipants(profile=member_of("folgaria"))),
    )

    assert await run(skill, "query_participant_profile") == {
        "community": {"key": "folgaria", "name": "Folgaria REC"},
        "user_id": "alice",
    }


# @verifies REQ-0027
async def test_a_profile_without_a_membership_still_answers(monkeypatch):
    skill = build(
        monkeypatch,
        FakeDTClient(participants=FakeParticipants(profile=member_of(None))),
    )

    assert await run(skill, "query_participant_profile") == {"user_id": "alice"}


# --- participant metrics ----------------------------------------------------


def meter_readings() -> Page:
    return Page(
        [
            Item(consumption_kwh=1.0, production_kwh=3.0),
            Item(consumption_kwh=2.0, production_kwh=0.5),
        ]
    )


# @verifies REQ-0028
async def test_meter_readings_are_summed_over_the_window(monkeypatch):
    skill = build(
        monkeypatch,
        FakeDTClient(
            participants=FakeParticipants(
                assets=with_sensors("meter-1"),
                values={"meters_data": meter_readings()},
            )
        ),
    )

    result = await run(skill, "query_participant_metrics", hours=6)

    assert result["consumption_kwh"] == 3.0
    assert result["production_kwh"] == 3.5
    assert result["data_points"] == 2
    assert result["window_hours"] == 6


async def test_self_consumption_is_summed_per_interval(monkeypatch):
    """Energy is only self-consumed if it is used when it is produced, so the overlap is
    per reading and then summed.

    Taking `min` of the window-wide totals instead would credit midday solar against
    evening load: here that would report 3.0 kWh and a rate of 1.0, for a household that
    actually matched 1.5.

    @verifies REQ-0028
    """
    skill = build(
        monkeypatch,
        FakeDTClient(
            participants=FakeParticipants(
                assets=with_sensors("meter-1"),
                values={"meters_data": meter_readings()},
            )
        ),
    )

    result = await run(skill, "query_participant_metrics")

    # min(1.0, 3.0) + min(2.0, 0.5)
    assert result["self_consumption_kwh"] == 1.5
    assert result["self_consumption_rate"] == 0.5


async def test_every_meter_is_queried_and_the_readings_combined(monkeypatch):
    """A participant with two meters is asking about their household, not about one
    device. Reporting the first meter's readings as the total was wrong by however much
    the second one measured, and said nothing about it.

    @verifies REQ-0028
    """
    participants = FakeParticipants(
        assets=with_sensors("meter-1", "meter-2"),
        values={"meters_data": meter_readings()},
    )
    skill = build(monkeypatch, FakeDTClient(participants=participants))

    result = await run(skill, "query_participant_metrics")

    assert result["device_ids"] == ["meter-1", "meter-2"]
    fetches = [c for c in participants.calls if c[0] == "fetch_values"]
    assert [f[1]["payload"]["device_id"] for f in fetches] == ["meter-1", "meter-2"]
    # Both meters' readings, summed.
    assert result["consumption_kwh"] == 6.0
    assert result["data_points"] == 4


# @verifies REQ-0028
async def test_a_participant_with_no_meter_is_told_so(monkeypatch):
    skill = build(monkeypatch, FakeDTClient(participants=FakeParticipants(assets=Page())))

    assert await run(skill, "query_participant_metrics") == {
        "error": "No energy assets found for this user."
    }


async def test_an_empty_window_is_a_message_rather_than_zeroes(monkeypatch):
    """Reporting 0 kWh for "no data" would be a wrong number; the model is given a
    sentence instead, which it can pass on honestly.

    @verifies REQ-0028
    """
    skill = build(
        monkeypatch,
        FakeDTClient(participants=FakeParticipants(assets=with_sensors("meter-1"))),
    )

    result = await run(skill, "query_participant_metrics")
    assert result["message"] == "No meter data available for this period."
    assert result["device_ids"] == ["meter-1"]
    assert "consumption_kwh" not in result


@pytest.mark.parametrize("hours", [0, -5])
# @verifies REQ-0028
async def test_a_non_positive_window_is_floored_at_one_hour(monkeypatch, hours):
    participants = FakeParticipants(
        assets=with_sensors("meter-1"), values={"meters_data": meter_readings()}
    )
    skill = build(monkeypatch, FakeDTClient(participants=participants))

    result = await run(skill, "query_participant_metrics", hours=hours)

    assert result["window_start_utc"] < result["window_end_utc"]


# @verifies REQ-0028
async def test_an_unreadable_value_counts_as_zero_rather_than_failing(monkeypatch):
    skill = build(
        monkeypatch,
        FakeDTClient(
            participants=FakeParticipants(
                assets=with_sensors("meter-1"),
                values={
                    "meters_data": Page(
                        [Item(consumption_kwh="n/a", production_kwh=None)]
                    )
                },
            )
        ),
    )

    result = await run(skill, "query_participant_metrics")
    assert result["consumption_kwh"] == 0.0
    assert result["production_kwh"] == 0.0


# --- community metrics ------------------------------------------------------


# @verifies REQ-0028
async def test_community_metrics_are_summed_and_rated(monkeypatch):
    skill = build(
        monkeypatch,
        FakeDTClient(
            participants=FakeParticipants(profile=member_of("folgaria")),
            communities=FakeCommunities(
                values={
                    "rec_self_consumption": Page(
                        [
                            Item(
                                total_consumption_kwh=100.0,
                                total_production_kwh=80.0,
                                self_consumption_kwh=25.0,
                            )
                        ]
                    )
                }
            ),
        ),
    )

    result = await run(skill, "query_community_metrics", days=7)

    assert result["community_id"] == "folgaria"
    assert result["self_consumption_rate"] == 0.25


# @verifies REQ-0028
async def test_a_participant_with_no_community_cannot_ask_about_one(monkeypatch):
    skill = build(
        monkeypatch,
        FakeDTClient(participants=FakeParticipants(profile=member_of(None))),
    )

    assert await run(skill, "query_community_metrics") == {
        "error": "User is not a member of any community."
    }


# --- failure handling -------------------------------------------------------


async def test_an_upstream_failure_becomes_a_tool_result_not_an_exception(monkeypatch):
    """The loop is streaming by the time a tool runs; raising would abort the answer
    mid-sentence. Every skill returns its failure as JSON instead.

    @verifies REQ-0028
    """
    skill = build(
        monkeypatch,
        FakeDTClient(
            participants=FakeParticipants(raises={"profile": RuntimeError("502 upstream")})
        ),
    )

    assert await run(skill, "query_participant_profile") == {"error": "502 upstream"}


# @verifies REQ-0025
async def test_an_unknown_tool_name_is_a_structured_error(monkeypatch):
    skill = build(monkeypatch, FakeDTClient())
    assert await run(skill, "query_something_else") == {
        "error": "Unknown tool: query_something_else"
    }
