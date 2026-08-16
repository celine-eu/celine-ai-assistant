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

LOCATION_ID = "it_folgaria"


def _safe_float(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _str(val: Any) -> str:
    return str(val) if val is not None else ""


def _normalize_temp(val: Any) -> float:
    t = _safe_float(val)
    if t > 100:
        return round(t - 273.15, 1)
    return t


class WeatherSkill(Skill):

    name = "weather"
    description = "Query weather conditions, forecasts, alerts, and energy forecasts."

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
                    "name": "get_weather_current",
                    "description": (
                        "Get the current weather conditions for the user's community location: "
                        "temperature, humidity, UV index, cloud cover, wind, and sunrise/sunset times."
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
                    "name": "get_weather_forecast",
                    "description": (
                        "Get a 7-day weather forecast with daily min/max temperatures, "
                        "precipitation probability, cloud cover, UV index, and conditions. "
                        "Use when the user asks about weather for tomorrow, this week, or upcoming days."
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
                    "name": "get_weather_alerts",
                    "description": (
                        "Check for active weather alerts (storms, heat waves, etc.) "
                        "in the user's community area."
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
                    "name": "get_energy_forecast",
                    "description": (
                        "Get today's hourly energy forecast including the community net exchange "
                        "(solar surplus) and the user's individual consumption forecast with "
                        "confidence bounds. Use when the user asks about energy trends, "
                        "when to consume, when to start appliances, or optimal usage times."
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
            if tool_name == "get_weather_current":
                return await self._weather_current(on_progress)
            if tool_name == "get_weather_forecast":
                return await self._weather_forecast(on_progress)
            if tool_name == "get_weather_alerts":
                return await self._weather_alerts(on_progress)
            if tool_name == "get_energy_forecast":
                return await self._energy_forecast(on_progress)
        except Exception as exc:
            log.error(
                "weather_skill_failed: tool=%s user=%s error=%s",
                tool_name, self._user_id, exc,
                exc_info=True,
            )
            return json.dumps({"error": str(exc)})

        return json.dumps({"error": f"Unknown tool: {tool_name}"})

    async def _notify(self, cb: ProgressCallback | None, msg: str) -> None:
        if cb:
            await cb(msg)

    async def _resolve_community_id(self) -> str | None:
        participant = await self._dt.participants.profile(self._user_id)
        membership = getattr(participant, "membership", None)
        community = getattr(membership, "community", None)
        return getattr(community, "key", None)

    async def _weather_current(self, on_progress: ProgressCallback | None) -> str:
        await self._notify(on_progress, "Fetching current weather...")
        community_id = await self._resolve_community_id()
        if not community_id:
            return json.dumps({"error": "User is not a member of any community."})

        res = await self._dt.communities.fetch_values(
            community_id=community_id,
            fetcher_id="weather_current",
            payload={"location_id": LOCATION_ID},
        )

        if not res or res.count == 0:
            return json.dumps({"message": "No current weather data available."})

        r = res.items[0].to_dict()
        return json.dumps({
            "temp_celsius": _normalize_temp(r.get("temp")),
            "humidity_percent": _safe_int(r.get("humidity")),
            "uv_index": _safe_float(r.get("uvi")),
            "clouds_percent": _safe_int(r.get("clouds")),
            "wind_direction_deg": _safe_int(r.get("wind_deg")),
            "condition": _str(r.get("weather_main")),
            "description": _str(r.get("weather_description")),
            "sunrise": _str(r.get("sunrise")),
            "sunset": _str(r.get("sunset")),
        }, ensure_ascii=False)

    async def _weather_forecast(self, on_progress: ProgressCallback | None) -> str:
        await self._notify(on_progress, "Fetching weather forecast...")
        community_id = await self._resolve_community_id()
        if not community_id:
            return json.dumps({"error": "User is not a member of any community."})

        now = datetime.now(timezone.utc)
        today_midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
        week_end = today_midnight + timedelta(days=8)

        daily_res, irradiance_res = await asyncio.gather(
            self._dt.communities.fetch_values(
                community_id=community_id,
                fetcher_id="weather_daily",
                payload={
                    "location_id": LOCATION_ID,
                    "start": today_midnight.isoformat(),
                    "end": week_end.isoformat(),
                },
            ),
            self._dt.communities.fetch_values(
                community_id=community_id,
                fetcher_id="weather_irradiance_hourly",
                payload={
                    "start": now.replace(hour=5, minute=0, second=0, microsecond=0).isoformat(),
                    "end": (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0).isoformat(),
                },
            ),
        )

        days = []
        if daily_res and daily_res.count > 0:
            for item in daily_res.items:
                r = item.to_dict()
                ts = r.get("ts") or r.get("datetime") or ""
                if isinstance(ts, datetime):
                    date_str = ts.date().isoformat()
                else:
                    date_str = _str(ts)[:10]
                day = {
                    "date": date_str,
                    "temp_min": _normalize_temp(r.get("temp_min")),
                    "temp_max": _normalize_temp(r.get("temp_max")),
                    "temp_day": _normalize_temp(r.get("temp_day")),
                    "precipitation_probability": _safe_float(r.get("pop")),
                    "clouds_percent": _safe_int(r.get("clouds")),
                    "uv_index": _safe_float(r.get("uvi")),
                    "condition": _str(r.get("weather_main")),
                    "description": _str(r.get("weather_description")),
                }
                rain = r.get("rain")
                if rain is not None:
                    day["rain_mm"] = _safe_float(rain)
                summary = _str(r.get("summary"))
                if summary:
                    day["summary"] = summary
                days.append(day)

        irradiance = []
        if irradiance_res and irradiance_res.count > 0:
            for item in irradiance_res.items:
                r = item.to_dict()
                irradiance.append({
                    "ts": _str(r.get("datetime") or r.get("ts") or ""),
                    "shortwave_radiation": _safe_float(r.get("shortwave_radiation")),
                    "global_tilted_irradiance": _safe_float(r.get("global_tilted_irradiance")),
                    "cloud_cover": _safe_float(r.get("cloud_cover")),
                })

        return json.dumps({
            "daily_forecast": days,
            "today_irradiance_hourly": irradiance,
        }, ensure_ascii=False)

    async def _weather_alerts(self, on_progress: ProgressCallback | None) -> str:
        await self._notify(on_progress, "Checking weather alerts...")
        community_id = await self._resolve_community_id()
        if not community_id:
            return json.dumps({"error": "User is not a member of any community."})

        res = await self._dt.communities.fetch_values(
            community_id=community_id,
            fetcher_id="weather_alerts",
            payload={"location_id": LOCATION_ID},
        )

        alerts = []
        if res and res.count > 0:
            for item in res.items:
                r = item.to_dict()
                alerts.append({
                    "event": _str(r.get("event")),
                    "sender": _str(r.get("sender_name")),
                    "start": _str(r.get("start_ts")),
                    "end": _str(r.get("end_ts")),
                    "description": _str(r.get("description")),
                })

        return json.dumps({
            "active_alerts": alerts,
            "count": len(alerts),
        }, ensure_ascii=False)

    async def _energy_forecast(self, on_progress: ProgressCallback | None) -> str:
        await self._notify(on_progress, "Fetching energy forecast...")

        device_id: str | None = None
        try:
            assets = await self._dt.participants.assets(self._user_id)
            for asset in getattr(assets, "items", []) or []:
                sensor_id = getattr(asset, "sensor_id", None)
                if sensor_id:
                    device_id = sensor_id
                    break
        except Exception as exc:
            log.warning("weather_skill_assets_failed: %s", exc)

        now = datetime.now(timezone.utc)
        today_05 = now.replace(hour=5, minute=0, second=0, microsecond=0)
        tomorrow_midnight = (today_05 + timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        payload_window = {
            "start": today_05.isoformat(),
            "end": tomorrow_midnight.isoformat(),
        }

        async def fetch_net_exchange():
            try:
                return await self._dt.participants.fetch_values(
                    participant_id=self._user_id,
                    fetcher_id="total_meters_forecast",
                    payload=payload_window,
                )
            except Exception as exc:
                log.warning("total_meters_forecast fetch failed: %s", exc)
                return None

        async def fetch_consumption():
            if not device_id:
                return None
            try:
                return await self._dt.participants.fetch_values(
                    participant_id=self._user_id,
                    fetcher_id="meter_forecast",
                    payload={"device_id": device_id, **payload_window},
                )
            except Exception as exc:
                log.warning("meter_forecast fetch failed: %s", exc)
                return None

        net_res, cons_res = await asyncio.gather(
            fetch_net_exchange(), fetch_consumption()
        )

        community_net_exchange: list[dict[str, Any]] = []
        if net_res and net_res.count > 0:
            for item in net_res.items:
                r = item.to_dict()
                community_net_exchange.append({
                    "ts": _str(r.get("timestamp") or r.get("datetime") or ""),
                    "net_exchange_kwh": _safe_float(r.get("net_exchange_kwh")),
                    "period": _str(r.get("period")) or "forecast",
                })

        user_consumption: list[dict[str, Any]] = []
        if cons_res and cons_res.count > 0:
            for item in cons_res.items:
                r = item.to_dict()
                entry: dict[str, Any] = {
                    "ts": _str(r.get("timestamp") or r.get("datetime") or ""),
                    "consumption_kwh": _safe_float(r.get("total_consumption_kwh")),
                    "period": _str(r.get("period")) or "forecast",
                }
                lower = r.get("total_consumption_lower")
                upper = r.get("total_consumption_upper")
                if lower is not None:
                    entry["lower_bound"] = _safe_float(lower)
                if upper is not None:
                    entry["upper_bound"] = _safe_float(upper)
                user_consumption.append(entry)

        now_iso = now.isoformat()
        upcoming_surplus = [
            h for h in community_net_exchange
            if h["net_exchange_kwh"] > 0 and h["ts"] >= now_iso
        ]
        upcoming_surplus.sort(key=lambda h: h["net_exchange_kwh"], reverse=True)
        best_upcoming = upcoming_surplus[:3]

        # Renamed here, so read the suggestion off *this* list and not off the raw rows
        # it was built from — those are still keyed `net_exchange_kwh`.
        best_upcoming_hours = [
            {"ts": h["ts"], "surplus_kwh": h["net_exchange_kwh"]} for h in best_upcoming
        ]

        result: dict[str, Any] = {
            "current_time_utc": now_iso,
            "community_net_exchange": community_net_exchange,
            "user_consumption_forecast": user_consumption,
            "best_upcoming_hours": best_upcoming_hours,
        }
        if best_upcoming_hours:
            top = best_upcoming_hours[0]
            result["suggestion"] = (
                f"The best upcoming hour to run appliances is {top['ts']} "
                f"with {top['surplus_kwh']:.2f} kWh of solar surplus. "
                "Suggest this specific time to the user rather than a wide window."
            )
        else:
            # Every remaining case is the same advice: whether the day's surplus has
            # already passed or there was never any, there is nothing left to shift to.
            result["suggestion"] = (
                "No solar surplus expected in the upcoming hours. "
                "There is no optimal time to shift consumption right now."
            )

        return json.dumps(result, ensure_ascii=False)

    def get_system_prompt_fragment(self) -> str | None:
        return (
            "**Weather & Forecast** (`get_weather_current`, `get_weather_forecast`, "
            "`get_weather_alerts`, `get_energy_forecast`): "
            "Use these tools when the user asks about weather, temperature, rain, "
            "UV index, irradiance, weather alerts, energy forecasts, consumption trends, "
            "or when they should run appliances / consume energy. "
            "`get_energy_forecast` returns the top upcoming surplus hours ranked by value. "
            "When advising on appliance timing, suggest the single best upcoming hour "
            "(from `best_upcoming_hours`), not a wide time range. "
            "If no surplus is expected soon, say so honestly."
        )
