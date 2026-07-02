from __future__ import annotations

import json
import logging
from typing import Any

from .base import ProgressCallback, Skill

log = logging.getLogger(__name__)


class SkillRegistry:

    def __init__(self) -> None:
        self._skills: dict[str, Skill] = {}

    def register(self, skill: Skill) -> None:
        self._skills[skill.name] = skill

    def unregister(self, name: str) -> None:
        self._skills.pop(name, None)

    @property
    def skills(self) -> dict[str, Skill]:
        return dict(self._skills)

    def get_tools(self) -> list[dict[str, Any]]:
        tools: list[dict[str, Any]] = []
        for skill in self._skills.values():
            for tool in skill.get_tools():
                fn = tool.setdefault("function", {})
                fn["strict"] = True
                params = fn.setdefault("parameters", {"type": "object"})
                params["additionalProperties"] = False
                props = params.get("properties", {})
                params["required"] = list(props.keys())
                tools.append(tool)
        return tools

    def get_system_prompt_fragments(self) -> list[str]:
        fragments: list[str] = []
        for skill in self._skills.values():
            f = skill.get_system_prompt_fragment()
            if f:
                fragments.append(f)
        return fragments

    async def execute(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        on_progress: ProgressCallback | None = None,
    ) -> str:
        for skill in self._skills.values():
            if skill.handles(tool_name):
                log.debug("skill_%s_handling_%s", skill.name, tool_name)
                return await skill.execute(
                    tool_name, arguments, on_progress=on_progress
                )
        log.warning("no_skill_handles_%s", tool_name)
        return json.dumps({"error": f"Unknown tool: {tool_name}"})
