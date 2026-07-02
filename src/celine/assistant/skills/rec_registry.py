from __future__ import annotations

import json
import logging
from typing import Any

from celine.sdk.rec_registry import RecRegistryUserClient

from .base import ProgressCallback, Skill

log = logging.getLogger(__name__)


def _schema_to_dict(obj: Any) -> dict:
    if obj is None:
        return {}
    if hasattr(obj, "model_dump"):
        return obj.model_dump(mode="json", exclude_none=True)
    if hasattr(obj, "to_dict"):
        return obj.to_dict()
    return {"value": str(obj)}


class RecRegistrySkill(Skill):

    name = "rec_registry"
    description = "Query user's REC membership, community, assets, and delivery points."

    def __init__(self, *, registry_base_url: str, user_token: str) -> None:
        self._client = RecRegistryUserClient(
            base_url=registry_base_url,
            default_token=user_token,
        )

    def get_tools(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "get_my_rec_profile",
                    "description": (
                        "Get the current user's REC profile: membership status, "
                        "role, community name, and basic information."
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
                    "name": "get_my_community_details",
                    "description": (
                        "Get details about the user's Renewable Energy Community (REC): "
                        "name, location, member count, configuration."
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
                    "name": "get_my_assets",
                    "description": (
                        "List the user's registered energy assets in the REC: "
                        "PV panels, smart meters, batteries, etc. "
                        "Returns asset keys, types, sensor IDs, and configuration."
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
                    "name": "get_my_asset_detail",
                    "description": (
                        "Get detailed information about a specific asset "
                        "owned by the user. Use get_my_assets first to discover asset keys."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "asset_key": {
                                "type": "string",
                                "description": "The asset key identifier.",
                            },
                        },
                        "required": ["asset_key"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_my_delivery_points",
                    "description": (
                        "List the user's delivery points (POD codes, connection points) "
                        "registered in the REC."
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
            if tool_name == "get_my_rec_profile":
                return await self._profile(on_progress)
            if tool_name == "get_my_community_details":
                return await self._community(on_progress)
            if tool_name == "get_my_assets":
                return await self._assets(on_progress)
            if tool_name == "get_my_asset_detail":
                return await self._asset_detail(arguments["asset_key"], on_progress)
            if tool_name == "get_my_delivery_points":
                return await self._delivery_points(on_progress)
        except Exception as exc:
            log.warning("rec_registry_skill_failed", extra={"tool": tool_name, "error": str(exc)})
            return json.dumps({"error": str(exc)})

        return json.dumps({"error": f"Unknown tool: {tool_name}"})

    async def _profile(self, on_progress: ProgressCallback | None) -> str:
        if on_progress:
            await on_progress("Fetching your REC profile...")
        me = await self._client.get_me()
        return json.dumps(_schema_to_dict(me), ensure_ascii=False, default=str)

    async def _community(self, on_progress: ProgressCallback | None) -> str:
        if on_progress:
            await on_progress("Fetching community details...")
        community = await self._client.get_my_community()
        return json.dumps(_schema_to_dict(community), ensure_ascii=False, default=str)

    async def _assets(self, on_progress: ProgressCallback | None) -> str:
        if on_progress:
            await on_progress("Fetching your assets...")
        assets = await self._client.get_my_assets()
        return json.dumps(_schema_to_dict(assets), ensure_ascii=False, default=str)

    async def _asset_detail(self, asset_key: str, on_progress: ProgressCallback | None) -> str:
        if on_progress:
            await on_progress(f"Fetching asset {asset_key}...")
        asset = await self._client.get_my_asset(asset_key)
        return json.dumps(_schema_to_dict(asset), ensure_ascii=False, default=str)

    async def _delivery_points(self, on_progress: ProgressCallback | None) -> str:
        if on_progress:
            await on_progress("Fetching your delivery points...")
        dps = await self._client.get_my_delivery_points()
        return json.dumps(_schema_to_dict(dps), ensure_ascii=False, default=str)

    def get_system_prompt_fragment(self) -> str | None:
        return (
            "**REC Registry** (`get_my_rec_profile`, `get_my_community_details`, "
            "`get_my_assets`, `get_my_asset_detail`, `get_my_delivery_points`): "
            "Use these tools when the user asks about their REC membership, "
            "community details, registered assets (PV panels, meters, batteries), "
            "or delivery points (POD codes). Use `get_my_assets` to discover "
            "asset keys before calling `get_my_asset_detail`."
        )
