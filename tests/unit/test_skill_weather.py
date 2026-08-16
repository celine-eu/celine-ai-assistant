"""Weather and the energy forecast.

The energy forecast is the skill behind "when should I run the washing machine", and
the answer it hands the model is a ranked shortlist rather than a window — a decision
recorded in ADR-0004.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from celine.assistant.skills import weather as weather_module
from celine.assistant.skills.weather import WeatherSkill, _normalize_temp
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

NOW = datetime(2026, 8, 15, 9, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def frozen_now(monkeypatch):
    class Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW

    monkeypatch.setattr(weather_module, "datetime", Frozen)
    return NOW


def build(monkeypatch, client: FakeDTClient) -> WeatherSkill:
    install_dt(monkeypatch, weather_module, client)
    return WeatherSkill(dt_base_url="http://dt.test", user_token="tok", user_id="alice")


async def run(skill: WeatherSkill, tool: str, **args) -> dict:
    return json.loads(await skill.execute(tool, args))


def hour(h: int) -> str:
    return datetime(2026, 8, 15, h, 0, 0, tzinfo=timezone.utc).isoformat()


# --- unit conversion --------------------------------------------------------


@pytest.mark.parametrize(
    ("given", "expected"),
    [(21.5, 21.5), (0, 0.0), (-4.0, -4.0), (100, 100.0), (294.15, 21.0)],
)
def test_a_temperature_above_100_is_assumed_to_be_kelvin(given, expected):
    """The upstream fetcher is inconsistent about units, so the skill guesses from the
    magnitude. It is a heuristic: an actual 300 °C reading would come back as 26.9.
    Nothing on this planet's weather makes that reachable.

    @verifies REQ-0028
    """
    assert _normalize_temp(given) == expected


# @verifies REQ-0028
def test_an_unreadable_temperature_becomes_zero_not_an_error():
    assert _normalize_temp(None) == 0.0
    assert _normalize_temp("warm") == 0.0


# --- current conditions -----------------------------------------------------


# @verifies REQ-0028
async def test_current_conditions_are_flattened_for_the_model(monkeypatch):
    skill = build(
        monkeypatch,
        FakeDTClient(
            participants=FakeParticipants(profile=member_of("folgaria")),
            communities=FakeCommunities(
                values={
                    "weather_current": Page(
                        [
                            Item(
                                temp=294.15,
                                humidity="61",
                                uvi=4.2,
                                clouds=20,
                                weather_main="Clear",
                            )
                        ]
                    )
                }
            ),
        ),
    )

    result = await run(skill, "get_weather_current")

    assert result["temp_celsius"] == 21.0
    assert result["humidity_percent"] == 61
    assert result["condition"] == "Clear"
    assert result["sunrise"] == ""


# @verifies REQ-0028
async def test_weather_needs_a_community_to_locate_the_user(monkeypatch):
    skill = build(
        monkeypatch,
        FakeDTClient(participants=FakeParticipants(profile=member_of(None))),
    )

    assert await run(skill, "get_weather_current") == {
        "error": "User is not a member of any community."
    }


# @verifies REQ-0028
async def test_no_readings_is_a_message_rather_than_a_zeroed_report(monkeypatch):
    skill = build(
        monkeypatch,
        FakeDTClient(participants=FakeParticipants(profile=member_of("folgaria"))),
    )

    assert await run(skill, "get_weather_current") == {
        "message": "No current weather data available."
    }


# @verifies REQ-0028
async def test_alerts_report_their_own_count(monkeypatch):
    skill = build(
        monkeypatch,
        FakeDTClient(
            participants=FakeParticipants(profile=member_of("folgaria")),
            communities=FakeCommunities(
                values={
                    "weather_alerts": Page(
                        [Item(event="Thunderstorm", sender_name="Meteo TN")]
                    )
                }
            ),
        ),
    )

    result = await run(skill, "get_weather_alerts")
    assert result["count"] == 1
    assert result["active_alerts"][0]["event"] == "Thunderstorm"


# @verifies REQ-0028
async def test_no_alerts_is_an_empty_list_and_not_an_error(monkeypatch):
    skill = build(
        monkeypatch,
        FakeDTClient(participants=FakeParticipants(profile=member_of("folgaria"))),
    )

    assert await run(skill, "get_weather_alerts") == {"active_alerts": [], "count": 0}


# --- energy forecast --------------------------------------------------------


def forecast_client(rows: list[Item], sensors=("meter-1",)) -> FakeDTClient:
    return FakeDTClient(
        participants=FakeParticipants(
            assets=with_sensors(*sensors),
            values={"total_meters_forecast": Page(rows)},
        )
    )


async def test_the_best_upcoming_hours_are_ranked_by_surplus(monkeypatch, frozen_now):
    """The shortlist is renamed on the way out — `net_exchange_kwh` becomes
    `surplus_kwh` — and the advice is built from the renamed list, not from the raw rows
    it came from.

    @verifies REQ-0028
    """
    skill = build(
        monkeypatch,
        forecast_client(
            [
                Item(timestamp=hour(11), net_exchange_kwh=2.0),
                Item(timestamp=hour(13), net_exchange_kwh=9.0),
                Item(timestamp=hour(12), net_exchange_kwh=5.0),
                Item(timestamp=hour(14), net_exchange_kwh=1.0),
            ]
        ),
    )

    result = await run(skill, "get_energy_forecast")

    assert [h["surplus_kwh"] for h in result["best_upcoming_hours"]] == [9.0, 5.0, 2.0]
    assert result["best_upcoming_hours"][0]["ts"] == hour(13)
    assert "9.00 kWh" in result["suggestion"]
    assert "rather than a wide window" in result["suggestion"]


async def test_the_shortlist_is_capped_at_three(monkeypatch, frozen_now):
    """A wide window is what the assistant is told not to give; the cap is what stops
    the model reconstructing one from the list.

    @verifies REQ-0028
    """
    skill = build(
        monkeypatch,
        forecast_client(
            [Item(timestamp=hour(h), net_exchange_kwh=float(h)) for h in range(10, 20)]
        ),
    )

    result = await run(skill, "get_energy_forecast")
    assert len(result["best_upcoming_hours"]) == 3


# @verifies REQ-0028
async def test_hours_already_past_are_not_offered(monkeypatch, frozen_now):
    skill = build(
        monkeypatch,
        forecast_client(
            [
                Item(timestamp=hour(6), net_exchange_kwh=20.0),
                Item(timestamp=hour(13), net_exchange_kwh=1.0),
            ]
        ),
    )

    result = await run(skill, "get_energy_forecast")

    assert [h["ts"] for h in result["best_upcoming_hours"]] == [hour(13)]
    assert len(result["community_net_exchange"]) == 2


# @verifies REQ-0028
async def test_a_forecast_with_no_surplus_at_all_says_there_is_none(
    monkeypatch, frozen_now
):
    skill = build(
        monkeypatch,
        forecast_client([Item(timestamp=hour(13), net_exchange_kwh=-2.0)]),
    )

    result = await run(skill, "get_energy_forecast")

    assert result["best_upcoming_hours"] == []
    assert "No solar surplus expected" in result["suggestion"]


async def test_a_surplus_that_is_entirely_in_the_past_still_gets_advice(
    monkeypatch, frozen_now
):
    """A morning of surplus that has already gone is, for advice purposes, the same as
    no surplus at all: there is nothing left to shift consumption into. Saying nothing
    would leave the model to invent the advice.

    @verifies REQ-0028
    """
    skill = build(
        monkeypatch,
        forecast_client([Item(timestamp=hour(6), net_exchange_kwh=20.0)]),
    )

    result = await run(skill, "get_energy_forecast")

    assert result["best_upcoming_hours"] == []
    assert "No solar surplus expected" in result["suggestion"]


async def test_a_participant_with_no_meter_still_gets_the_community_forecast(
    monkeypatch, frozen_now
):
    """Consumption needs a device; the community's net exchange does not. Losing one
    must not lose the other.

    @verifies REQ-0028
    """
    client = FakeDTClient(
        participants=FakeParticipants(
            assets=Page(),
            values={"total_meters_forecast": Page([Item(timestamp=hour(6), net_exchange_kwh=4.0)])},
        )
    )
    skill = build(monkeypatch, client)

    result = await run(skill, "get_energy_forecast")

    assert result["user_consumption_forecast"] == []
    assert len(result["community_net_exchange"]) == 1


async def test_a_failing_consumption_fetch_does_not_lose_the_community_forecast(
    monkeypatch, frozen_now
):
    """The two fetches are gathered; one raising must not take the other with it.

    @verifies REQ-0028
    """
    client = FakeDTClient(
        participants=FakeParticipants(
            assets=with_sensors("meter-1"),
            values={"total_meters_forecast": Page([Item(timestamp=hour(6), net_exchange_kwh=4.0)])},
            raises={"meter_forecast": RuntimeError("504")},
        )
    )
    skill = build(monkeypatch, client)

    result = await run(skill, "get_energy_forecast")
    assert len(result["community_net_exchange"]) == 1
    assert result["user_consumption_forecast"] == []


# @verifies REQ-0028
async def test_consumption_bounds_are_carried_through_only_when_present(
    monkeypatch, frozen_now
):
    client = FakeDTClient(
        participants=FakeParticipants(
            assets=with_sensors("meter-1"),
            values={
                "meter_forecast": Page(
                    [
                        Item(
                            timestamp=hour(13),
                            total_consumption_kwh=1.2,
                            total_consumption_lower=0.9,
                            total_consumption_upper=1.5,
                        ),
                        Item(timestamp=hour(14), total_consumption_kwh=1.0),
                    ]
                )
            },
        )
    )
    skill = build(monkeypatch, client)

    bounded, unbounded = (await run(skill, "get_energy_forecast"))[
        "user_consumption_forecast"
    ]

    assert bounded["lower_bound"] == 0.9
    assert "lower_bound" not in unbounded
    assert unbounded["period"] == "forecast"
