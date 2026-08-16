"""The API suite runs against `FakeHistoryStore`, not `HistoryStore`.

That is only honest for as long as the two agree on their public surface. `HistoryStore`
reaches `AsyncSessionLocal` directly rather than taking a session, so it cannot be
pointed at a test database with `app.dependency_overrides` the way `../dataset-api` does
— the double is the only option, and this file is what stops it drifting into fiction.

What it cannot check is behaviour: that `list_conversations` really orders by last
message, that a delete really cascades. Those need a database. See
`.agents/plans/first-test-suite.md`.
"""

from __future__ import annotations

import inspect

import pytest

from celine.assistant.history import HistoryStore
from tests.conftest import FakeHistoryStore

PUBLIC = [
    name
    for name, _ in inspect.getmembers(HistoryStore, inspect.isfunction)
    if not name.startswith("_")
]


# @verifies REQ-0010
def test_the_real_store_still_has_the_methods_we_think_it_has():
    assert sorted(PUBLIC) == [
        "append_message",
        "conversation_exists",
        "delete_attachment_any",
        "delete_conversation",
        "get_attachment_any",
        "get_or_create_conversation",
        "list_attachments_for_user",
        "list_conversations",
        "list_messages",
        "record_attachment",
    ]


@pytest.mark.parametrize("name", PUBLIC)
# @verifies REQ-0010
def test_the_double_implements_every_method_with_the_same_signature(name):
    assert hasattr(FakeHistoryStore, name), f"the double is missing {name}"

    real = inspect.signature(getattr(HistoryStore, name))
    fake = inspect.signature(getattr(FakeHistoryStore, name))

    assert list(real.parameters) == list(fake.parameters)
    for parameter in real.parameters.values():
        assert fake.parameters[parameter.name].kind == parameter.kind
        assert fake.parameters[parameter.name].default == parameter.default


@pytest.mark.parametrize("name", PUBLIC)
# @verifies REQ-0010
def test_every_method_is_async_on_both(name):
    assert inspect.iscoroutinefunction(getattr(HistoryStore, name))
    assert inspect.iscoroutinefunction(getattr(FakeHistoryStore, name))
