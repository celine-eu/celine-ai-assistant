from __future__ import annotations

import json
import logging
import math
from datetime import datetime, timezone
from typing import Any

from celine.sdk.auth.static import StaticTokenProvider
from celine.sdk.dt import DTClient
from celine.sdk.flexibility import FlexibilityClient

from .base import ProgressCallback, Skill

log = logging.getLogger(__name__)

POINTS_PER_LEVEL = 100


def _safe_float(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


class FlexibilitySkill(Skill):

    name = "flexibility"
    description = "Query flexibility suggestions, gamification points, and engagement opportunities."

    def __init__(
        self,
        *,
        flexibility_base_url: str,
        dt_base_url: str,
        user_token: str,
        user_id: str,
    ) -> None:
        self._flex = FlexibilityClient(
            base_url=flexibility_base_url,
            default_token=user_token,
        )
        self._dt = DTClient(
            base_url=dt_base_url,
            token_provider=StaticTokenProvider(user_token),
        )
        self._user_id = user_id

    def get_tools(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "get_flexibility_suggestions",
                    "description": (
                        "Get current load-shift opportunities the user can accept to earn points. "
                        "Each suggestion has a time window, estimated energy impact (kWh), "
                        "and reward points. Use when the user asks how to earn points, "
                        "about flexibility suggestions, or wants to know what actions are available."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {},
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_gamification_status",
                    "description": (
                        "Get the user's gamification status: total points, level, "
                        "community ranking, earned badges, and daily points history. "
                        "Use when the user asks about their points, level, rank, badges, "
                        "or engagement progress."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {},
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_commitment_history",
                    "description": (
                        "Get the user's history of flexibility commitments: accepted, "
                        "settled, or cancelled. Shows estimated vs actual points earned. "
                        "Use when the user asks about past actions, commitment history, "
                        "or how many points they earned from flexibility."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {},
                    },
                },
            },
        ]

    async def execute(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        on_progress: ProgressCallback | None = None,
    ) -> str:
        try:
            if tool_name == "get_flexibility_suggestions":
                return await self._suggestions(on_progress)
            if tool_name == "get_gamification_status":
                return await self._gamification(on_progress)
            if tool_name == "get_commitment_history":
                return await self._commitment_history(on_progress)
        except Exception as exc:
            log.error(
                "flexibility_skill_failed: tool=%s user=%s error=%s",
                tool_name, self._user_id, exc,
                exc_info=True,
            )
            return json.dumps({"error": str(exc)})

        return json.dumps({"error": f"Unknown tool: {tool_name}"})

    async def _notify(self, cb: ProgressCallback | None, msg: str) -> None:
        if cb:
            await cb(msg)

    async def _resolve_device_id(self) -> str:
        try:
            assets = await self._dt.participants.assets(self._user_id)
            for asset in getattr(assets, "items", []) or []:
                sensor_id = getattr(asset, "sensor_id", None)
                if sensor_id:
                    return sensor_id
        except Exception as exc:
            log.warning("flexibility_skill_assets_failed: %s", exc)
        return ""

    async def _suggestions(self, on_progress: ProgressCallback | None) -> str:
        await self._notify(on_progress, "Fetching flexibility suggestions...")
        items = await self._flex.list_suggestions()

        now = datetime.now(timezone.utc)
        suggestions = []
        for item in items:
            period_end = item.period_end
            if isinstance(period_end, str):
                try:
                    end_dt = datetime.fromisoformat(period_end.replace("Z", "+00:00"))
                    if end_dt.tzinfo is None:
                        end_dt = end_dt.replace(tzinfo=timezone.utc)
                    if end_dt < now:
                        continue
                except ValueError:
                    pass

            suggestions.append({
                "id": item.id,
                "type": item.suggestion_type,
                "period_start": item.period_start,
                "period_end": item.period_end,
                "time_window": item.clock_range,
                "target_period": item.to_period,
                "target_time": item.to_time,
                "is_tomorrow": item.to_is_tomorrow,
                "impact_kwh": item.impact_kwh_estimated,
                "reward_points": item.reward_points,
                "confidence": item.confidence,
            })

        result: dict[str, Any] = {
            "suggestions": suggestions,
            "count": len(suggestions),
        }
        if suggestions:
            best = max(suggestions, key=lambda s: s["reward_points"])
            result["best_opportunity"] = {
                "time_window": best["time_window"],
                "reward_points": best["reward_points"],
                "impact_kwh": best["impact_kwh"],
            }
            result["tip"] = (
                f"The best opportunity right now is worth {best['reward_points']} points "
                f"during {best['time_window']}. Shifting consumption to this window "
                f"could save ~{best['impact_kwh']:.1f} kWh."
            )
        else:
            result["tip"] = "No flexibility opportunities available right now. Check back later."

        return json.dumps(result, ensure_ascii=False)

    async def _gamification(self, on_progress: ProgressCallback | None) -> str:
        await self._notify(on_progress, "Fetching gamification status...")

        device_id = await self._resolve_device_id()

        total_points = 0
        daily_points: list[dict[str, Any]] = []
        if device_id:
            try:
                pts_res = await self._dt.participants.fetch_values(
                    participant_id=self._user_id,
                    fetcher_id="rec_participant_points",
                    payload={"device_id": device_id},
                )
                if pts_res and pts_res.count > 0:
                    for item in pts_res.items:
                        d = item.to_dict()
                        day = str(d.get("ts_date", ""))
                        pts = int(d.get("daily_points") or 0)
                        total_points += pts
                        daily_points.append({"date": day, "points": pts})
                    daily_points.sort(key=lambda x: x["date"])
            except Exception as exc:
                log.warning("rec_participant_points fetch failed: %s", exc)

        level = max(1, total_points // POINTS_PER_LEVEL + 1)
        next_level_at = level * POINTS_PER_LEVEL

        ranking: dict[str, Any] | None = None
        if device_id:
            try:
                today = datetime.now(timezone.utc).date().isoformat()
                res = await self._dt.participants.fetch_values(
                    participant_id=self._user_id,
                    fetcher_id="rec_gamification_summary",
                    payload={"device_id": device_id, "date": today},
                )
                if res and res.count > 0:
                    d = res.items[0].to_dict()
                    position = int(d.get("rank_position", 1))
                    total = max(int(d.get("total_members", 1)), 1)
                    ranking = {
                        "position": position,
                        "total_members": total,
                        "top_percent": math.ceil(position / total * 100),
                    }
            except Exception as exc:
                log.warning("rec_gamification_summary fetch failed: %s", exc)

        result: dict[str, Any] = {
            "total_points": total_points,
            "level": level,
            "next_level_at": next_level_at,
            "points_to_next_level": next_level_at - total_points,
        }
        if ranking:
            result["ranking"] = ranking
        if daily_points:
            result["recent_daily_points"] = daily_points[-7:]

        return json.dumps(result, ensure_ascii=False)

    async def _commitment_history(self, on_progress: ProgressCallback | None) -> str:
        await self._notify(on_progress, "Fetching commitment history...")

        commitments_res = await self._flex.list_commitments(limit=20)

        device_id = await self._resolve_device_id()
        real_daily_points: dict[str, int] = {}
        if device_id:
            try:
                pts_res = await self._dt.participants.fetch_values(
                    participant_id=self._user_id,
                    fetcher_id="rec_participant_points",
                    payload={"device_id": device_id},
                )
                if pts_res and pts_res.count > 0:
                    for item in pts_res.items:
                        d = item.to_dict()
                        day = str(d.get("ts_date", ""))
                        real_daily_points[day] = int(d.get("daily_points") or 0)
            except Exception as exc:
                log.warning("rec_participant_points fetch failed for history: %s", exc)

        items = []
        total_earned = 0
        for row in commitments_res.items:
            actual_pts = row.reward_points_actual
            if row.status.value == "settled" and real_daily_points:
                day = row.period_start.isoformat()[:10]
                actual_pts = real_daily_points.get(day, 0)

            items.append({
                "id": str(row.id),
                "type": row.suggestion_type,
                "period_start": row.period_start.isoformat(),
                "period_end": row.period_end.isoformat(),
                "committed_at": row.committed_at.isoformat(),
                "status": row.status.value,
                "points_estimated": row.reward_points_estimated,
                "points_actual": actual_pts,
            })
            if actual_pts:
                total_earned += actual_pts

        return json.dumps({
            "commitments": items,
            "total_commitments": len(items),
            "total_points_earned": total_earned,
        }, ensure_ascii=False)

    def get_system_prompt_fragment(self) -> str | None:
        return (
            "**Flexibility & Points** (`get_flexibility_suggestions`, `get_gamification_status`, "
            "`get_commitment_history`): "
            "Use these tools when the user asks about earning points, their level or ranking, "
            "flexibility opportunities, how to participate, or their commitment history. "
            "`get_flexibility_suggestions` returns active load-shift windows the user can accept "
            "to earn reward points — each has a specific time window, estimated kWh impact, "
            "and reward points. Combine with weather/energy forecast data to give richer advice "
            "about when and why to shift consumption. "
            "When the user asks 'when should I use appliances' or 'how can I earn points', "
            "call both `get_flexibility_suggestions` and `get_energy_forecast` to give advice "
            "that covers both solar surplus timing and points opportunities."
        )
