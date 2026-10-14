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


def reading(export: float, imported: float, self_consumed: float | None = None) -> Item:
    """One 15-minute row of `meters_data`, under the names the gold table gives it.

    `production_kwh` is what the exchange meter (M1) exported and `consumption_kwh` what
    it imported. `self_consumed_kwh` is the production meter (M2) minus the export — and
    is the negative of the export wherever M2 has no reading.
    """
    fields = {"production_kwh": export, "consumption_kwh": imported}
    if self_consumed is not None:
        fields["self_consumed_kwh"] = self_consumed
    return Item(**fields)


def with_m2() -> Page:
    return Page([reading(3.0, 0.0, 1.0), reading(0.0, 2.0, 0.0)])


def m1_only() -> Page:
    return Page([reading(3.0, 1.0, -3.0), reading(0.0, 2.0, 0.0)])


def metrics_skill(monkeypatch, values, sensors=("meter-1",)):
    participants = FakeParticipants(
        assets=with_sensors(*sensors), values={"meters_data": values}
    )
    return build(monkeypatch, FakeDTClient(participants=participants)), participants


# @verifies REQ-0028
async def test_meter_readings_are_summed_over_the_window(monkeypatch):
    skill, _ = metrics_skill(monkeypatch, with_m2())

    result = await run(skill, "query_participant_metrics", hours=6)

    assert result["grid_export_kwh"] == 3.0
    assert result["grid_import_kwh"] == 2.0
    assert result["data_points"] == 2
    assert result["window_hours"] == 6


async def test_production_is_export_plus_what_was_self_consumed(monkeypatch):
    """The gold columns are named after production and consumption but hold the grid
    exchange. Reported as they are, a household that made 4 kWh and used 3 was told it
    made 3 and used 2 — and that 2 % of it was self-consumed.

    @verifies REQ-0028
    """
    skill, _ = metrics_skill(monkeypatch, with_m2())

    result = await run(skill, "query_participant_metrics")

    assert result["production_kwh"] == 4.0
    assert result["self_consumption_kwh"] == 1.0
    assert result["consumption_kwh"] == 3.0
    assert result["self_consumption_rate"] == 0.25
    assert result["self_sufficiency_rate"] == 0.3333


async def test_an_interval_missing_its_m2_reading_does_not_cancel_its_export(monkeypatch):
    """Where M2 has no reading, the gold row carries `self_consumed = -export`. Taken
    literally it would subtract the export from production; what is known is only that
    production was at least the export.

    @verifies REQ-0028
    """
    skill, _ = metrics_skill(
        monkeypatch, Page([reading(2.0, 0.0, -2.0), reading(1.0, 0.0, 3.0)])
    )

    result = await run(skill, "query_participant_metrics")

    assert result["production_kwh"] == 6.0
    assert result["self_consumption_kwh"] == 3.0


async def test_without_a_production_meter_only_the_grid_exchange_is_reported(monkeypatch):
    """An M1-only meter sees the grid and nothing behind it, so production and
    self-consumption are unknown, not zero and not negative. No `production_kwh` key is
    sent: given one, the model reports the export as what the panels made.

    @verifies REQ-0028
    """
    skill, _ = metrics_skill(monkeypatch, m1_only())

    result = await run(skill, "query_participant_metrics")

    assert result["grid_export_kwh"] == 3.0
    assert result["grid_import_kwh"] == 3.0
    for key in ("production_kwh", "consumption_kwh", "self_consumption_kwh",
                "self_consumption_rate", "self_sufficiency_rate"):
        assert key not in result
    assert result["devices_without_production_meter"] == ["meter-1"]
    assert "not measured" in result["note"]


async def test_every_meter_is_queried_and_the_readings_combined(monkeypatch):
    """A participant with two meters is asking about their household, not about one
    device. Reporting the first meter's readings as the total was wrong by however much
    the second one measured, and said nothing about it.

    @verifies REQ-0028
    """
    skill, participants = metrics_skill(
        monkeypatch, with_m2(), sensors=("meter-1", "meter-2")
    )

    result = await run(skill, "query_participant_metrics")

    assert result["device_ids"] == ["meter-1", "meter-2"]
    fetches = [c for c in participants.calls if c[0] == "fetch_values"]
    assert [f[1]["payload"]["device_id"] for f in fetches] == ["meter-1", "meter-2"]
    # Both meters' readings, summed.
    assert result["consumption_kwh"] == 6.0
    assert result["data_points"] == 4


async def test_production_covers_only_the_meters_that_measure_it(monkeypatch):
    """With one M1+M2 meter and one M1-only, production is the first meter's and the
    second is named, so the model does not present a part as the whole.

    @verifies REQ-0028
    """
    pages = {"meter-1": with_m2(), "meter-2": m1_only()}
    skill, _ = metrics_skill(
        monkeypatch,
        lambda payload: pages[payload["device_id"]],
        sensors=("meter-1", "meter-2"),
    )

    result = await run(skill, "query_participant_metrics")

    assert result["production_kwh"] == 4.0
    assert result["grid_export_kwh"] == 6.0
    assert result["grid_import_kwh"] == 5.0
    assert result["devices_without_production_meter"] == ["meter-2"]
    assert "meter-2" in result["note"]


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
    skill, _ = metrics_skill(monkeypatch, with_m2())

    result = await run(skill, "query_participant_metrics", hours=hours)

    assert result["window_start_utc"] < result["window_end_utc"]


# @verifies REQ-0028
async def test_an_unreadable_value_counts_as_zero_rather_than_failing(monkeypatch):
    skill, _ = metrics_skill(
        monkeypatch,
        Page([Item(consumption_kwh="n/a", production_kwh=None, self_consumed_kwh="x")]),
    )

    result = await run(skill, "query_participant_metrics")
    assert result["grid_import_kwh"] == 0.0
    assert result["grid_export_kwh"] == 0.0


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
