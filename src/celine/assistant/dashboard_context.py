from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import Request

from celine.sdk.auth.static import StaticTokenProvider
from celine.sdk.dt import DTClient

from .auth import UserIdentity, extract_access_token
from .settings import settings

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


def _format_metric(label: str, value: float | None, unit: str = "kWh") -> str:
    if value is None:
        return f"- {label}: unavailable"
    return f"- {label}: {value:.2f} {unit}"


def _format_ratio(label: str, value: float | None) -> str:
    if value is None:
        return f"- {label}: unavailable"
    return f"- {label}: {value * 100:.1f}%"


async def build_dashboard_context(
    request: Request,
    user: UserIdentity,
) -> dict | None:
    raw_token = extract_access_token(request)
    if not raw_token or not settings.digital_twin_api_url:
        return None

    dt = DTClient(
        base_url=settings.digital_twin_api_url,
        token_provider=StaticTokenProvider(raw_token),
    )

    try:
        participant = await dt.participants.profile(user.user_id)
    except Exception as exc:
        log.warning("dashboard_context_profile_failed", extra={"error": str(exc)})
        return None

    membership = getattr(participant, "membership", None)
    community = getattr(membership, "community", None)
    community_id = getattr(community, "key", None)
    if not community_id:
        return None

    device_ids: list[str] = []
    try:
        assets = await dt.participants.assets(user.user_id)
        for asset in getattr(assets, "items", []) or []:
            sensor_id = getattr(asset, "sensor_id", None)
            if sensor_id:
                device_ids.append(sensor_id)
    except Exception as exc:
        log.warning("dashboard_context_assets_failed", extra={"error": str(exc)})

    now = datetime.now(timezone.utc)
    twelve_hours_ago = now - timedelta(hours=12)
    trend_start = now - timedelta(days=7)

    user_metrics = {
        "production_kwh": None,
        "consumption_kwh": None,
        "self_consumption_kwh": None,
        "self_consumption_rate": None,
    }
    rec_metrics = {
        "production_kwh": None,
        "consumption_kwh": None,
        "self_consumption_kwh": None,
        "self_consumption_rate": None,
    }

    if device_ids:
        try:
            meters_response = await dt.participants.fetch_values(
                participant_id=user.user_id,
                fetcher_id="meters_data",
                payload={
                    "device_id": device_ids[0],
                    "start": twelve_hours_ago.isoformat(),
                    "end": now.isoformat(),
                },
            )
            items = getattr(meters_response, "items", []) or []
            if items:
                total_consumption_kw = sum(
                    _safe_float(item.to_dict().get("consumption_kw")) for item in items
                )
                total_production_kw = sum(
                    _safe_float(item.to_dict().get("production_kw")) for item in items
                )
                interval_hours = 0.25
                production_kwh = total_production_kw * interval_hours
                consumption_kwh = total_consumption_kw * interval_hours
                self_consumption_kwh = min(production_kwh, consumption_kwh)
                user_metrics = {
                    "production_kwh": production_kwh,
                    "consumption_kwh": consumption_kwh,
                    "self_consumption_kwh": self_consumption_kwh,
                    "self_consumption_rate": _safe_ratio(
                        self_consumption_kwh, consumption_kwh
                    ),
                }
        except Exception as exc:
            log.warning("dashboard_context_user_values_failed", extra={"error": str(exc)})

    try:
        rec_response = await dt.communities.fetch_values(
            community_id=community_id,
            fetcher_id="rec_self_consumption",
            payload={
                "start": trend_start.isoformat(),
                "end": now.isoformat(),
            },
        )
        items = getattr(rec_response, "items", []) or []
        if items:
            total_rec_consumption = sum(
                _safe_float(item.to_dict().get("total_consumption_kw"))
                for item in items
            )
            total_rec_production = sum(
                _safe_float(item.to_dict().get("total_production_kw"))
                for item in items
            )
            total_rec_self_consumption = sum(
                _safe_float(item.to_dict().get("self_consumption_kw"))
                for item in items
            )
            rec_metrics = {
                "production_kwh": total_rec_production,
                "consumption_kwh": total_rec_consumption,
                "self_consumption_kwh": total_rec_self_consumption,
                "self_consumption_rate": _safe_ratio(
                    total_rec_self_consumption,
                    total_rec_consumption,
                ),
            }
    except Exception as exc:
        log.warning("dashboard_context_rec_values_failed", extra={"error": str(exc)})

    lines = [
        "Authenticated user dashboard context. Use these values when the user asks about the dashboard, Panoramica, overview, their energy values, or REC KPIs.",
        "If the user's request conflicts with these values, prefer the live dashboard context over generic explanations.",
        f"- generated_at_utc: {now.isoformat()}",
        f"- user_metrics_window_start_utc: {twelve_hours_ago.isoformat()}",
        f"- rec_metrics_window_start_utc: {trend_start.isoformat()}",
        f"- assets_detected: {len(device_ids)}",
        "",
        "User dashboard metrics:",
        _format_metric("production", user_metrics["production_kwh"]),
        _format_metric("consumption", user_metrics["consumption_kwh"]),
        _format_metric(
            "self_consumption", user_metrics["self_consumption_kwh"]
        ),
        _format_ratio(
            "self_consumption_rate", user_metrics["self_consumption_rate"]
        ),
        "",
        "REC dashboard metrics:",
        _format_metric("production", rec_metrics["production_kwh"]),
        _format_metric("consumption", rec_metrics["consumption_kwh"]),
        _format_metric("self_consumption", rec_metrics["self_consumption_kwh"]),
        _format_ratio("self_consumption_rate", rec_metrics["self_consumption_rate"]),
        "",
        "Metric semantics:",
        "- 'Panoramica' is the overview dashboard page for these metrics.",
        "- user metrics are derived from the participant meters_data fetcher over the last 12 hours.",
        "- REC metrics are derived from the community rec_self_consumption fetcher over the last 7 days.",
        "- user self-consumption is computed as min(production, consumption) on the aggregated user window.",
    ]

    return {
        "source": "dashboard_context",
        "title": "User dashboard context",
        "text": "\n".join(lines),
        "score": 1.0,
        "metadata": {
            "kind": "dashboard_context",
            "hidden": True,
        },
    }
