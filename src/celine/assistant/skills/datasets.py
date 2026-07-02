from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from .base import ProgressCallback, Skill

log = logging.getLogger(__name__)


class DatasetSkill(Skill):

    name = "datasets"
    description = "Query governed datasets via the dataset API."

    def __init__(self, *, datasets_base_url: str, user_token: str) -> None:
        self._base_url = datasets_base_url.rstrip("/")
        self._token = user_token

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token}"}

    def get_tools(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "list_datasets",
                    "description": (
                        "List available datasets the user can query. Returns dataset "
                        "names, descriptions, and available columns."
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
                    "name": "query_dataset",
                    "description": (
                        "Execute a SQL query against a governed dataset. "
                        "Use list_datasets first to discover available tables and columns. "
                        "Queries are read-only and subject to the user's data access policies."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "dataset": {
                                "type": "string",
                                "description": "The dataset name to query.",
                            },
                            "sql": {
                                "type": "string",
                                "description": (
                                    "SQL SELECT query to execute. Must be a read-only query. "
                                    "Use the table name from list_datasets."
                                ),
                            },
                            "limit": {
                                "type": "integer",
                                "description": "Max rows to return. Default 100.",
                                "default": 100,
                            },
                        },
                        "required": ["dataset", "sql"],
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
            if tool_name == "list_datasets":
                return await self._list_datasets(on_progress)
            if tool_name == "query_dataset":
                return await self._query_dataset(
                    arguments["dataset"],
                    arguments["sql"],
                    arguments.get("limit", 100),
                    on_progress,
                )
        except Exception as exc:
            log.warning("dataset_skill_failed", extra={"tool": tool_name, "error": str(exc)})
            return json.dumps({"error": str(exc)})

        return json.dumps({"error": f"Unknown tool: {tool_name}"})

    async def _list_datasets(self, on_progress: ProgressCallback | None) -> str:
        if on_progress:
            await on_progress("Fetching available datasets...")

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                f"{self._base_url}/datasets",
                headers=self._headers(),
            )
            resp.raise_for_status()
            return resp.text

    async def _query_dataset(
        self,
        dataset: str,
        sql: str,
        limit: int,
        on_progress: ProgressCallback | None,
    ) -> str:
        if on_progress:
            await on_progress(f"Querying dataset '{dataset}'...")

        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                f"{self._base_url}/datasets/{dataset}/query",
                headers=self._headers(),
                json={"sql": sql, "limit": min(limit, 500)},
            )
            resp.raise_for_status()

            data = resp.json()
            result_text = json.dumps(data, ensure_ascii=False, default=str)
            if len(result_text) > 8000:
                rows = data.get("rows", data.get("results", []))
                while len(json.dumps(data, default=str)) > 8000 and len(rows) > 3:
                    rows.pop()
                data["truncated"] = True
                result_text = json.dumps(data, ensure_ascii=False, default=str)

            return result_text

    def get_system_prompt_fragment(self) -> str | None:
        return (
            "**Datasets** (`list_datasets`, `query_dataset`): "
            "Use these tools to query structured energy data. First call `list_datasets` "
            "to discover available tables, then use `query_dataset` with a SQL SELECT query. "
            "This is useful for historical data analysis, trends, and comparisons."
        )
