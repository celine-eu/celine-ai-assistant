"""A tool that changes anything runs only on the member's confirmation (REQ-0055).

No confirmation flow exists in the app yet, so today the effect is that a writing tool
is refused: the model gets a tool error it can explain, and nothing is sent upstream.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from celine.assistant.settings import settings as real_settings
from celine.assistant.skills import Skill, SkillRegistry
from celine.assistant.skills.datasets import DatasetSkill
from celine.assistant.skills.factory import build_skill_registry
from celine.assistant.skills.registry import confirmation_key


def tool(name: str, writes: Any) -> dict:
    t: dict[str, Any] = {
        "type": "function",
        "function": {
            "name": name,
            "description": name,
            "parameters": {"type": "object", "properties": {}},
        },
    }
    if writes is not None:
        t["writes"] = writes
    return t


class RecordingSkill(Skill):
    name = "recording"

    def __init__(self, tools: list[dict]):
        self._tools = tools
        self.calls: list[tuple[str, dict]] = []

    def get_tools(self) -> list[dict]:
        return self._tools

    async def execute(self, tool_name, arguments, *, on_progress=None) -> str:
        self.calls.append((tool_name, arguments))
        return json.dumps({"ok": tool_name})


def registry(skill: Skill, **kwargs) -> SkillRegistry:
    r = SkillRegistry(**kwargs)
    r.register(skill)
    return r


# --- every tool says whether it writes ------------------------------------------


def every_skill() -> list[Skill]:
    built = build_skill_registry(
        user_token="t",
        user_id="u",
        community_id="c",
        history_store=None,
        settings=real_settings.model_copy(
            update={
                "digital_twin_api_url": "http://dt.test",
                "rec_registry_api_url": "http://rec.test",
                "flexibility_api_url": "http://flex.test",
            }
        ),
    )
    return [
        *built.skills.values(),
        DatasetSkill(datasets_base_url="http://ds.test", user_token="t"),
    ]


# @verifies REQ-0055
def test_every_tool_of_every_skill_declares_whether_it_writes():
    for skill in every_skill():
        for t in skill.get_tools():
            assert isinstance(t.get("writes"), bool), t["function"]["name"]


# @verifies REQ-0055
def test_every_active_tool_reads_and_the_dataset_query_writes():
    writes = {
        t["function"]["name"]: t["writes"]
        for skill in every_skill()
        for t in skill.get_tools()
    }

    assert writes.pop("query_dataset") is True
    assert writes.pop("list_datasets") is False
    assert writes and not any(writes.values())


# @verifies REQ-0055
def test_the_attribute_is_not_sent_to_the_model():
    declared = [tool("read_it", False)]
    r = registry(RecordingSkill(declared))

    (emitted,) = r.get_tools()

    assert "writes" not in emitted
    assert declared[0]["writes"] is False  # the skill's own declaration is kept


# --- execution -----------------------------------------------------------------------


# @verifies REQ-0055
async def test_a_reading_tool_runs():
    skill = RecordingSkill([tool("read_it", False)])

    assert json.loads(await registry(skill).execute("read_it", {})) == {"ok": "read_it"}
    assert skill.calls == [("read_it", {})]


@pytest.mark.parametrize("writes", [True, None, "no"])
async def test_a_writing_or_undeclared_tool_is_refused_without_confirmation(writes):
    """An undeclared or malformed attribute counts as writing: forgetting it must not
    be the way a writing tool gets in.

    @verifies REQ-0055
    """
    skill = RecordingSkill([tool("change_it", writes)])

    result = json.loads(await registry(skill).execute("change_it", {"x": 1}))

    assert skill.calls == []
    assert result["confirmation_required"] is True
    assert "confirm" in result["error"]
    assert "change_it" in result["error"]


# @verifies REQ-0055
async def test_a_confirmed_call_runs_once_with_exactly_the_confirmed_arguments():
    skill = RecordingSkill([tool("change_it", True)])
    r = registry(skill, confirmed_calls=[("change_it", {"x": 1, "y": [2]})])

    other = json.loads(await r.execute("change_it", {"x": 2, "y": [2]}))
    first = json.loads(await r.execute("change_it", {"y": [2], "x": 1}))
    again = json.loads(await r.execute("change_it", {"x": 1, "y": [2]}))

    assert other["confirmation_required"] is True
    assert first == {"ok": "change_it"}
    assert again["confirmation_required"] is True
    assert skill.calls == [("change_it", {"y": [2], "x": 1})]


# @verifies REQ-0055
async def test_a_confirmation_names_one_tool():
    skill = RecordingSkill([tool("change_it", True), tool("change_that", True)])
    r = registry(skill, confirmed_calls=[("change_it", {})])

    result = json.loads(await r.execute("change_that", {}))

    assert result["confirmation_required"] is True
    assert skill.calls == []


def test_the_confirmation_key_ignores_argument_order_only():
    assert confirmation_key("t", {"a": 1, "b": 2}) == confirmation_key("t", {"b": 2, "a": 1})
    assert confirmation_key("t", {"a": 1}) != confirmation_key("t", {"a": "1"})
    assert confirmation_key("t", {}) != confirmation_key("u", {})


# @verifies REQ-0055
def test_no_request_carries_a_confirmation_today():
    """Nothing in the app can give one yet, so the per-request registry has none."""
    skill_registry = build_skill_registry(
        user_token="t", user_id="u", history_store=None, settings=real_settings
    )
    assert skill_registry.confirmed_calls == frozenset()
