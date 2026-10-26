from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from typing import Any

from .base import ProgressCallback, Skill

log = logging.getLogger(__name__)


def confirmation_key(tool_name: str, arguments: dict[str, Any]) -> str:
    """The identity of one tool call, as a member's confirmation names it.

    Argument order does not matter; argument values, types and the tool name do.
    """
    return json.dumps(
        [tool_name, arguments], sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )


def tool_writes(tool: dict[str, Any]) -> bool:
    """Whether a declared tool changes anything (REQ-0055).

    Every tool declares `"writes": bool` beside `"type"`. Anything but an explicit
    `False` counts as writing, so a tool that forgets the attribute is refused rather
    than let through.
    """
    return tool.get("writes") is not False


class SkillRegistry:
    """The tools offered for one request, and the only way they are run.

    `confirmed_calls` are the `(tool name, arguments)` pairs the member confirmed for
    this request. A writing tool runs only for an exact match, once (REQ-0055). The app
    has no confirmation flow yet, so every request builds a registry with none.
    """

    def __init__(
        self, *, confirmed_calls: Iterable[tuple[str, dict[str, Any]]] = ()
    ) -> None:
        self._skills: dict[str, Skill] = {}
        self._confirmed = {confirmation_key(n, a) for n, a in confirmed_calls}

    @property
    def confirmed_calls(self) -> frozenset[str]:
        """Confirmation keys still unused in this request."""
        return frozenset(self._confirmed)

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
                # `writes` is ours, not the API's: the copy sent drops it, the skill's
                # own declaration keeps it for `execute`.
                tools.append({k: v for k, v in tool.items() if k != "writes"})
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
            declared = next(
                (t for t in skill.get_tools() if t["function"]["name"] == tool_name),
                None,
            )
            if declared is not None:
                if tool_writes(declared) and not self._consume(tool_name, arguments):
                    log.warning("writing_tool_refused_unconfirmed: %s", tool_name)
                    return json.dumps({
                        "error": (
                            f"{tool_name} would change data, which needs the member's "
                            "confirmation in the app for this exact request. No "
                            "confirmation was given, so nothing was done. Tell the "
                            "member what you would have done instead."
                        ),
                        "confirmation_required": True,
                    })
                log.debug("skill_%s_handling_%s", skill.name, tool_name)
                return await skill.execute(
                    tool_name, arguments, on_progress=on_progress
                )
        log.warning("no_skill_handles_%s", tool_name)
        return json.dumps({"error": f"Unknown tool: {tool_name}"})

    def _consume(self, tool_name: str, arguments: dict[str, Any]) -> bool:
        key = confirmation_key(tool_name, arguments)
        if key not in self._confirmed:
            return False
        self._confirmed.discard(key)
        return True
