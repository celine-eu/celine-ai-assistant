"""The registry is the tool-calling surface. What it does to a skill's tool schema on
the way out is not obvious from either side, and is what most of this file pins.
"""

from __future__ import annotations

import json
from typing import Any

from celine.assistant.skills import Skill, SkillRegistry


class RecordingSkill(Skill):
    name = "recording"

    def __init__(self, tools: list[dict[str, Any]] | None = None, fragment: str | None = None):
        self._tools = tools if tools is not None else [tool("do_thing")]
        self._fragment = fragment
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def get_tools(self) -> list[dict[str, Any]]:
        return self._tools

    async def execute(self, tool_name, arguments, *, on_progress=None) -> str:
        self.calls.append((tool_name, arguments))
        if on_progress:
            await on_progress("working")
        return json.dumps({"ok": tool_name})

    def get_system_prompt_fragment(self) -> str | None:
        return self._fragment


def tool(name: str, properties: dict[str, Any] | None = None, required=None) -> dict:
    fn: dict[str, Any] = {"name": name, "description": name}
    params: dict[str, Any] = {"type": "object", "properties": properties or {}}
    if required is not None:
        params["required"] = required
    fn["parameters"] = params
    return {"type": "function", "function": fn}


# --- schema rewriting -------------------------------------------------------


# @verifies REQ-0026
def test_every_tool_is_emitted_strict_and_closed():
    registry = SkillRegistry()
    registry.register(RecordingSkill([tool("do_thing", {"a": {"type": "string"}})]))

    (emitted,) = registry.get_tools()
    fn = emitted["function"]

    assert fn["strict"] is True
    assert fn["parameters"]["additionalProperties"] is False


def test_every_declared_property_is_forced_required():
    """A skill's own `required` list is overwritten, not merged.

    `search_documents` declares `top_k` with a default and leaves it out of `required`;
    it comes out required anyway. OpenAI strict mode has no notion of an optional
    parameter, so this is deliberate — but it means a skill cannot express one, and
    every `execute` must therefore tolerate the argument being present.

    @verifies REQ-0026
    """
    registry = SkillRegistry()
    registry.register(
        RecordingSkill(
            [
                tool(
                    "do_thing",
                    {"a": {"type": "string"}, "b": {"type": "integer", "default": 5}},
                    required=["a"],
                )
            ]
        )
    )

    (emitted,) = registry.get_tools()
    assert sorted(emitted["function"]["parameters"]["required"]) == ["a", "b"]


# @verifies REQ-0026
def test_a_tool_with_no_properties_gets_an_empty_required_list():
    registry = SkillRegistry()
    registry.register(RecordingSkill([tool("do_thing")]))

    (emitted,) = registry.get_tools()
    assert emitted["function"]["parameters"]["required"] == []


def test_get_tools_rewrites_the_skill_s_own_dict_in_place():
    """The rewrite is a mutation, not a copy.

    Every skill in this repository builds its list fresh on each call, which is what
    makes that invisible. A skill that returned a module-level constant would find it
    permanently `strict` — including in its own unit tests. Pinned so the day someone
    caches the list, a test says why it broke.

    @verifies REQ-0026
    """
    declared = [tool("do_thing", {"a": {"type": "string"}})]
    registry = SkillRegistry()
    registry.register(RecordingSkill(declared))

    registry.get_tools()

    assert declared[0]["function"]["strict"] is True


# @verifies REQ-0026
def test_get_tools_is_idempotent():
    registry = SkillRegistry()
    registry.register(RecordingSkill([tool("do_thing", {"a": {"type": "string"}})]))

    assert registry.get_tools() == registry.get_tools()


# --- dispatch ---------------------------------------------------------------


# @verifies REQ-0025
async def test_a_call_is_routed_to_the_skill_that_declares_it():
    a = RecordingSkill([tool("alpha")])
    a.name = "a"
    b = RecordingSkill([tool("beta")])
    b.name = "b"

    registry = SkillRegistry()
    registry.register(a)
    registry.register(b)

    assert json.loads(await registry.execute("beta", {"x": 1})) == {"ok": "beta"}
    assert a.calls == []
    assert b.calls == [("beta", {"x": 1})]


async def test_an_undeclared_tool_is_a_structured_error_not_an_exception():
    """The model, not a person, chooses the tool name. A hallucinated one has to come
    back as something the model can read and recover from.

    @verifies REQ-0025
    """
    registry = SkillRegistry()
    registry.register(RecordingSkill())

    result = json.loads(await registry.execute("no_such_tool", {}))
    assert result == {"error": "Unknown tool: no_such_tool"}


# @verifies REQ-0025
async def test_progress_callbacks_reach_the_caller():
    seen: list[str] = []

    async def on_progress(msg: str) -> None:
        seen.append(msg)

    registry = SkillRegistry()
    registry.register(RecordingSkill())

    await registry.execute("do_thing", {}, on_progress=on_progress)
    assert seen == ["working"]


# --- registration -----------------------------------------------------------


# @verifies REQ-0027
def test_skills_are_keyed_by_name_so_a_re_register_replaces():
    registry = SkillRegistry()
    first, second = RecordingSkill(), RecordingSkill()
    registry.register(first)
    registry.register(second)

    assert list(registry.skills) == ["recording"]
    assert registry.skills["recording"] is second


# @verifies REQ-0027
def test_the_skills_mapping_is_a_copy():
    registry = SkillRegistry()
    registry.register(RecordingSkill())

    registry.skills.clear()
    assert list(registry.skills) == ["recording"]


# @verifies REQ-0027
def test_system_prompt_fragments_skip_the_skills_that_declare_none():
    quiet = RecordingSkill()
    quiet.name = "quiet"
    loud = RecordingSkill(fragment="**Loud**: does things.")
    loud.name = "loud"

    registry = SkillRegistry()
    registry.register(quiet)
    registry.register(loud)

    assert registry.get_system_prompt_fragments() == ["**Loud**: does things."]
