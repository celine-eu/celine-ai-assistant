from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from celine.sdk.auth.static import StaticTokenProvider
from celine.sdk.dt import DTClient

from .base import ProgressCallback, Skill

log = logging.getLogger(__name__)


def _safe_float(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_ratio(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator is None:
        return None
    if denominator <= 0:
        return 0.0
    return numerator / denominator


class DigitalTwinSkill(Skill):

    name = "digital_twin"
    description = "Query energy data from the Digital Twin."

    def __init__(self, *, dt_base_url: str, user_token: str, user_id: str) -> None:
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
                    "name": "query_participant_profile",
                    "description": (
                        "Get the current user's profile including their community membership, "
                        "assets, and basic information."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {},
                        "required": [],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "query_participant_metrics",
                    "description": (
                        "Query the user's energy metrics (production, consumption, self-consumption, "
                        "grid export and import) from their smart meters. Returns data for a "
                        "specified time window. Production and self-consumption are present only "
                        "for meters that measure them; read the `note` field when present."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "hours": {
                                "type": "integer",
                                "description": "Number of hours to look back. Default 12.",
                                "default": 12,
                            },
                        },
                        "required": [],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "query_community_metrics",
                    "description": (
                        "Query the REC (Renewable Energy Community) aggregate metrics: "
                        "total production, consumption, self-consumption, and self-consumption rate."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "days": {
                                "type": "integer",
                                "description": "Number of days to look back. Default 7.",
                                "default": 7,
                            },
                        },
                        "required": [],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "query_participant_assets",
                    "description": (
                        "List the user's registered energy assets (smart meters, "
                        "sensors, PV panels)."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {},
                        "required": [],
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
            if tool_name == "query_participant_profile":
                return await self._profile(on_progress)
            if tool_name == "query_participant_metrics":
                hours = arguments.get("hours", 12)
                return await self._participant_metrics(hours, on_progress)
            if tool_name == "query_community_metrics":
                days = arguments.get("days", 7)
                return await self._community_metrics(days, on_progress)
            if tool_name == "query_participant_assets":
                return await self._assets(on_progress)
        except Exception as exc:
            log.error(
                "dt_skill_failed: tool=%s user=%s error=%s",
                tool_name, self._user_id, exc,
                exc_info=True,
            )
            return json.dumps({"error": str(exc)})

        return json.dumps({"error": f"Unknown tool: {tool_name}"})

    async def _notify(self, cb: ProgressCallback | None, msg: str) -> None:
        if cb:
            await cb(msg)

    async def _profile(self, on_progress: ProgressCallback | None) -> str:
        await self._notify(on_progress, "Fetching participant profile...")
        participant = await self._dt.participants.profile(self._user_id)

        result: dict[str, Any] = {}
        membership = getattr(participant, "membership", None)
        community = getattr(membership, "community", None)

        if community:
            result["community"] = {
                "key": getattr(community, "key", None),
                "name": getattr(community, "name", None),
            }

        result["user_id"] = self._user_id
        return json.dumps(result, ensure_ascii=False, default=str)

    async def _participant_metrics(
        self, hours: int, on_progress: ProgressCallback | None
    ) -> str:
        log.info("dt_participant_metrics: user=%s hours=%d", self._user_id, hours)
        await self._notify(on_progress, "Fetching participant assets...")
        assets = await self._dt.participants.assets(self._user_id)
        device_ids: list[str] = []
        for asset in getattr(assets, "items", []) or []:
            sensor_id = getattr(asset, "sensor_id", None)
            if sensor_id:
                device_ids.append(sensor_id)

        log.info("dt_participant_metrics: found %d devices: %s", len(device_ids), device_ids)
        if not device_ids:
            return json.dumps({"error": "No energy assets found for this user."})

        now = datetime.now(timezone.utc)
        start = now - timedelta(hours=max(1, hours))

        await self._notify(on_progress, f"Querying meter data for last {hours}h...")
        log.info(
            "dt_fetch_values: participant=%s fetcher=meters_data devices=%s start=%s end=%s",
            self._user_id, device_ids, start.isoformat(), now.isoformat(),
        )

        # Every meter, not the first. A member with a second meter was previously told
        # one meter's readings as though they were their total, with nothing in the
        # response to say so.
        responses = await asyncio.gather(
            *(
                self._dt.participants.fetch_values(
                    participant_id=self._user_id,
                    fetcher_id="meters_data",
                    payload={
                        "device_id": device_id,
                        "start": start.isoformat(),
                        "end": now.isoformat(),
                    },
                )
                for device_id in device_ids
            )
        )

        readings = {
            device_id: getattr(response, "items", []) or []
            for device_id, response in zip(device_ids, responses)
        }
        data_points = sum(len(rows) for rows in readings.values())
        if not data_points:
            return json.dumps({
                "window_hours": hours,
                "device_ids": device_ids,
                "message": "No meter data available for this period.",
            })

        # The gold columns are named after production and consumption but hold what the
        # exchange meter (M1) saw: `production_kwh` is the grid export, `consumption_kwh`
        # the grid import. `self_consumed_kwh` is the production meter (M2) less the
        # export, and is the negative of the export wherever M2 has no reading.
        grid_export_kwh = 0.0
        grid_import_kwh = 0.0
        measured_export_kwh = 0.0
        measured_import_kwh = 0.0
        self_consumption_kwh = 0.0
        without_m2: list[str] = []
        for device_id in device_ids:
            export = imported = self_consumed = 0.0
            for item in readings[device_id]:
                row = item.to_dict()
                export += _safe_float(row.get("production_kwh"))
                imported += _safe_float(row.get("consumption_kwh"))
                # An interval without an M2 reading says only that production was at
                # least the export, so its negative self-consumption is dropped.
                self_consumed += max(_safe_float(row.get("self_consumed_kwh")), 0.0)
            grid_export_kwh += export
            grid_import_kwh += imported
            # A device has a production meter iff it ever saw self-consumption.
            if self_consumed > 0:
                measured_export_kwh += export
                measured_import_kwh += imported
                self_consumption_kwh += self_consumed
            elif readings[device_id]:
                without_m2.append(device_id)

        result: dict[str, Any] = {
            "window_hours": hours,
            "window_start_utc": start.isoformat(),
            "window_end_utc": now.isoformat(),
            "device_ids": device_ids,
            "grid_export_kwh": round(grid_export_kwh, 2),
            "grid_import_kwh": round(grid_import_kwh, 2),
            "data_points": data_points,
        }
        if self_consumption_kwh > 0:
            production_kwh = measured_export_kwh + self_consumption_kwh
            consumption_kwh = measured_import_kwh + self_consumption_kwh
            result.update({
                "production_kwh": round(production_kwh, 2),
                "consumption_kwh": round(consumption_kwh, 2),
                "self_consumption_kwh": round(self_consumption_kwh, 2),
                # Share of production used on site, and share of consumption covered by it.
                "self_consumption_rate": round(
                    _safe_ratio(self_consumption_kwh, production_kwh) or 0, 4
                ),
                "self_sufficiency_rate": round(
                    _safe_ratio(self_consumption_kwh, consumption_kwh) or 0, 4
                ),
            })
        if without_m2:
            result["devices_without_production_meter"] = without_m2
            result["note"] = (
                f"Meters {', '.join(without_m2)} have no production meter: their solar "
                "production, self-consumption and total consumption are not measured, only "
                "the energy exported to and imported from the grid. Do not present grid "
                "export as production. Without solar panels, grid import is the consumption."
            )

        return json.dumps(result, ensure_ascii=False)

    async def _community_metrics(
        self, days: int, on_progress: ProgressCallback | None
    ) -> str:
        log.info("dt_community_metrics: user=%s days=%d", self._user_id, days)
        await self._notify(on_progress, "Resolving community...")
        participant = await self._dt.participants.profile(self._user_id)
        membership = getattr(participant, "membership", None)
        community = getattr(membership, "community", None)
        community_id = getattr(community, "key", None)
        log.info("dt_community_metrics: community_id=%s", community_id)
        if not community_id:
            return json.dumps({"error": "User is not a member of any community."})

        now = datetime.now(timezone.utc)
        start = now - timedelta(days=max(1, days))

        await self._notify(
            on_progress,
            f"Querying community metrics for last {days} days...",
        )
        log.info(
            "dt_fetch_values: community=%s fetcher=rec_self_consumption start=%s end=%s",
            community_id, start.isoformat(), now.isoformat(),
        )
        rec_response = await self._dt.communities.fetch_values(
            community_id=community_id,
            fetcher_id="rec_self_consumption",
            payload={
                "start": start.isoformat(),
                "end": now.isoformat(),
            },
        )
        items = getattr(rec_response, "items", []) or []
        if not items:
            return json.dumps({
                "community_id": community_id,
                "window_days": days,
                "message": "No community data available for this period.",
            })

        total_consumption = sum(
            _safe_float(item.to_dict().get("total_consumption_kwh")) for item in items
        )
        total_production = sum(
            _safe_float(item.to_dict().get("total_production_kwh")) for item in items
        )
        total_self_consumption = sum(
            _safe_float(item.to_dict().get("self_consumption_kwh")) for item in items
        )

        return json.dumps({
            "community_id": community_id,
            "window_days": days,
            "window_start_utc": start.isoformat(),
            "window_end_utc": now.isoformat(),
            "production_kwh": round(total_production, 2),
            "consumption_kwh": round(total_consumption, 2),
            "self_consumption_kwh": round(total_self_consumption, 2),
            "self_consumption_rate": round(
                _safe_ratio(total_self_consumption, total_consumption) or 0, 4
            ),
            "data_points": len(items),
        }, ensure_ascii=False)

    async def _assets(self, on_progress: ProgressCallback | None) -> str:
        await self._notify(on_progress, "Fetching participant assets...")
        assets = await self._dt.participants.assets(self._user_id)
        items = []
        for asset in getattr(assets, "items", []) or []:
            items.append({
                "sensor_id": getattr(asset, "sensor_id", None),
                "asset_type": getattr(asset, "asset_type", None),
                "name": getattr(asset, "name", None),
            })
        return json.dumps({"assets": items}, ensure_ascii=False, default=str)

    def get_system_prompt_fragment(self) -> str | None:
        return (
            "**Energy Data** (`query_participant_metrics`, `query_community_metrics`, "
            "`query_participant_profile`, `query_participant_assets`): "
            "Use these tools to fetch live energy data when the user asks about their "
            "production, consumption, self-consumption, energy metrics, dashboard values, "
            "or REC/community performance. Always prefer querying live data over guessing."
        )
