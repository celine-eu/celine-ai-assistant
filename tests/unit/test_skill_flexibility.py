"""Load-shift suggestions and the points ledger."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from celine.assistant.skills import flexibility as flex_module
from celine.assistant.skills.flexibility import POINTS_PER_LEVEL, FlexibilitySkill
from tests.fakes import Attr, FakeDTClient, FakeParticipants, Item, Page, with_sensors

NOW = datetime.now(timezone.utc)


def suggestion(
    *,
    id="s1",
    reward_points=10,
    impact_kwh=1.5,
    community_kwh=40.0,
    ends_in_hours=2,
    clock_range="13:00–15:00",
):
    return Attr(
        id=id,
        suggestion_type="shift",
        period_start=(NOW).isoformat(),
        period_end=(NOW + timedelta(hours=ends_in_hours)).isoformat(),
        clock_range=clock_range,
        to_period="afternoon",
        to_time="13:00",
        to_is_tomorrow=False,
        impact_kwh_estimated=impact_kwh,
        reward_points=reward_points,
        community_kwh=community_kwh,
        confidence="high",
    )


def commitment(*, status="settled", estimated=10, actual=None, day="2026-08-14"):
    start = datetime.fromisoformat(f"{day}T13:00:00+00:00")
    return Attr(
        id=f"c-{day}",
        suggestion_type="shift",
        period_start=start,
        period_end=start + timedelta(hours=2),
        committed_at=start - timedelta(hours=6),
        status=Attr(value=status),
        reward_points_estimated=estimated,
        reward_points_actual=actual,
    )


class FakeFlexClient:
    def __init__(self, *, suggestions=None, commitments=None, **_ignored):
        self._suggestions = suggestions or []
        self._commitments = commitments or []

    async def list_suggestions(self):
        return list(self._suggestions)

    async def list_commitments(self, limit=20):
        return Page(list(self._commitments))


def build(monkeypatch, *, flex: FakeFlexClient, dt: FakeDTClient | None = None):
    monkeypatch.setattr(flex_module, "FlexibilityClient", lambda **kw: flex)
    monkeypatch.setattr(flex_module, "DTClient", lambda **kw: dt or FakeDTClient())
    return FlexibilitySkill(
        flexibility_base_url="http://flex.test",
        dt_base_url="http://dt.test",
        user_token="tok",
        user_id="alice",
    )


async def run(skill, tool, **args) -> dict:
    return json.loads(await skill.execute(tool, args))


# --- suggestions ------------------------------------------------------------


# @verifies REQ-0028
async def test_an_expired_suggestion_is_dropped(monkeypatch):
    skill = build(
        monkeypatch,
        flex=FakeFlexClient(
            suggestions=[
                suggestion(id="live", ends_in_hours=2),
                suggestion(id="stale", ends_in_hours=-2),
            ]
        ),
    )

    result = await run(skill, "get_flexibility_suggestions")

    assert [s["id"] for s in result["suggestions"]] == ["live"]
    assert result["count"] == 1


# @verifies REQ-0028
async def test_the_best_opportunity_is_the_one_worth_most_points(monkeypatch):
    skill = build(
        monkeypatch,
        flex=FakeFlexClient(
            suggestions=[
                suggestion(id="small", reward_points=5),
                suggestion(id="big", reward_points=25, clock_range="10:00–12:00"),
            ]
        ),
    )

    result = await run(skill, "get_flexibility_suggestions")

    assert result["best_opportunity"]["reward_points"] == 25
    assert "25 points" in result["tip"]
    assert "10:00–12:00" in result["tip"]


async def test_a_community_first_suggestion_is_pitched_on_community_benefit(monkeypatch):
    """When the member's own device has no usable forecast the estimate is `None`, and
    the advice switches from "you earn points" to "the community uses its own energy"
    rather than printing a blank.

    @verifies REQ-0028
    """
    skill = build(
        monkeypatch,
        flex=FakeFlexClient(
            suggestions=[
                suggestion(reward_points=None, impact_kwh=None, community_kwh=42.0)
            ]
        ),
    )

    result = await run(skill, "get_flexibility_suggestions")

    assert "42 kWh" in result["tip"]
    assert "helps the community" in result["tip"]


# @verifies REQ-0028
async def test_no_opportunities_is_still_useful_advice(monkeypatch):
    skill = build(monkeypatch, flex=FakeFlexClient(suggestions=[]))

    result = await run(skill, "get_flexibility_suggestions")

    assert result["count"] == 0
    assert "no_such_key" not in result
    assert result["tip"].startswith("No flexibility opportunities")


async def test_an_unparseable_period_end_keeps_the_suggestion(monkeypatch):
    """Dropping a suggestion because its timestamp is malformed would hide a live
    opportunity; the skill keeps it and lets the model read the raw window.

    @verifies REQ-0028
    """
    odd = suggestion(id="odd")
    odd.period_end = "not a timestamp"
    skill = build(monkeypatch, flex=FakeFlexClient(suggestions=[odd]))

    result = await run(skill, "get_flexibility_suggestions")
    assert [s["id"] for s in result["suggestions"]] == ["odd"]


# --- gamification -----------------------------------------------------------


SEASON = {"season_start": "2026-09-01", "season_end": "2026-11-01"}


def points_client(
    season_points: int | None = None,
    daily: list[Item] | None = None,
    sensors=("meter-1",),
    rank=(9, 44),
) -> FakeDTClient:
    values = {"rec_participant_points": Page(daily or [])}
    if season_points is not None:
        values["rec_points_leaderboard"] = Page(
            [
                Item(
                    **SEASON,
                    season_points=season_points,
                    season_rank=rank[0],
                    total_members=rank[1],
                )
            ]
        )
    return FakeDTClient(
        participants=FakeParticipants(assets=with_sensors(*sensors), values=values)
    )


@pytest.mark.parametrize(
    ("points", "level", "to_next"),
    [(0, 1, 100), (1, 1, 99), (99, 1, 1), (100, 2, 100), (250, 3, 50)],
)
async def test_the_level_is_derived_from_the_points(monkeypatch, points, level, to_next):
    """One level per `POINTS_PER_LEVEL`, starting at level 1.

    Crossing a boundary exactly resets the distance to a full level rather than zero,
    which is what makes 100 points read as "level 2, 100 to go".

    @verifies REQ-0028
    """
    assert POINTS_PER_LEVEL == 100
    skill = build(monkeypatch, flex=FakeFlexClient(), dt=points_client(points))

    result = await run(skill, "get_gamification_status")

    assert result["season_points"] == points
    assert result["level"] == level
    assert result["points_to_next_level"] == to_next


async def test_points_are_the_current_season_s_not_a_sum_of_the_daily_ledger(monkeypatch):
    """The daily ledger comes oldest-first and capped at 365 rows, so past a year its sum
    is the first year's — 758 for a member with 1219 this season. Lifetime totals are
    private by contract in any case; the season total is the published figure.

    @verifies REQ-0028
    """
    daily = [Item(ts_date="2025-09-01", daily_points=758)]
    skill = build(monkeypatch, flex=FakeFlexClient(), dt=points_client(1219, daily))

    result = await run(skill, "get_gamification_status")

    assert result["season_points"] == 1219
    assert result["level"] == 13
    assert result["season_start"] == "2026-09-01"
    assert result["season_end"] == "2026-11-01"
    assert "total_points" not in result


# @verifies REQ-0028
async def test_only_days_in_the_current_season_are_shown_as_recent(monkeypatch):
    daily = [Item(ts_date="2026-08-24", daily_points=33)] + [
        Item(ts_date=f"2026-09-{d:02d}", daily_points=d) for d in range(1, 11)
    ]
    skill = build(monkeypatch, flex=FakeFlexClient(), dt=points_client(55, daily))

    result = await run(skill, "get_gamification_status")

    assert len(result["recent_daily_points"]) == 7
    assert result["recent_daily_points"][0] == {"date": "2026-09-04", "points": 4}
    assert result["recent_daily_points"][-1] == {"date": "2026-09-10", "points": 10}


async def test_a_ledger_that_stops_before_the_season_shows_no_history(monkeypatch):
    """A truncated ledger ends in an old season; those days are not "recent".

    @verifies REQ-0028
    """
    daily = [Item(ts_date="2026-08-24", daily_points=33)]
    skill = build(monkeypatch, flex=FakeFlexClient(), dt=points_client(55, daily))

    result = await run(skill, "get_gamification_status")

    assert "recent_daily_points" not in result


async def test_a_participant_with_no_meter_scores_zero_rather_than_failing(monkeypatch):
    """Points are keyed on a device, so no device means no ledger to read. The status
    still answers — with a level, which is what the UI renders.

    @verifies REQ-0028
    """
    skill = build(
        monkeypatch,
        flex=FakeFlexClient(),
        dt=FakeDTClient(participants=FakeParticipants(assets=Page())),
    )

    result = await run(skill, "get_gamification_status")

    assert result == {
        "season_points": 0,
        "level": 1,
        "next_level_at": 100,
        "points_to_next_level": 100,
    }


# @verifies REQ-0028
async def test_the_ranking_is_the_season_points_rank(monkeypatch):
    skill = build(
        monkeypatch, flex=FakeFlexClient(), dt=points_client(1219, rank=(3, 40))
    )

    result = await run(skill, "get_gamification_status")
    assert result["ranking"] == {"position": 3, "total_members": 40, "top_percent": 8}


# --- commitment history -----------------------------------------------------


async def test_a_settled_commitment_is_re_scored_from_the_real_ledger(monkeypatch):
    """The flexibility service records what it estimated; the twin records what the
    meter actually did. For a settled commitment the meter wins.

    @verifies REQ-0028
    """
    skill = build(
        monkeypatch,
        flex=FakeFlexClient(
            commitments=[commitment(status="settled", estimated=10, actual=10)]
        ),
        dt=points_client(daily=[Item(ts_date="2026-08-14", daily_points=7)]),
    )

    result = await run(skill, "get_commitment_history")

    (row,) = result["commitments"]
    assert row["points_estimated"] == 10
    assert row["points_actual"] == 7
    assert result["total_points_earned"] == 7


# @verifies REQ-0028
async def test_an_unsettled_commitment_keeps_the_services_own_number(monkeypatch):
    skill = build(
        monkeypatch,
        flex=FakeFlexClient(
            commitments=[commitment(status="accepted", estimated=10, actual=None)]
        ),
        dt=points_client(daily=[Item(ts_date="2026-08-14", daily_points=7)]),
    )

    (row,) = (await run(skill, "get_commitment_history"))["commitments"]
    assert row["points_actual"] is None


# @verifies REQ-0028
async def test_a_settled_day_with_no_ledger_entry_scores_zero(monkeypatch):
    skill = build(
        monkeypatch,
        flex=FakeFlexClient(
            commitments=[commitment(status="settled", day="2026-08-14", actual=10)]
        ),
        dt=points_client(daily=[Item(ts_date="2026-08-01", daily_points=99)]),
    )

    (row,) = (await run(skill, "get_commitment_history"))["commitments"]
    assert row["points_actual"] == 0
