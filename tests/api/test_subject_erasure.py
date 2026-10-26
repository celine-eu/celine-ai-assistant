"""`POST /admin/subjects/erase`: who may call it, and what it answers.

What an erasure deletes is tested in `tests/unit/test_erasure.py`; this is the route
around it, with the service replaced where the answer is all that matters.
"""

from __future__ import annotations

import logging

import pytest

from celine.assistant import erasure
from tests.conftest import ADMIN_ID, PLATFORM_ADMIN, USER_ID

ERASER = "svc-erasure"
VICTIM = "subject-to-erase"


@pytest.fixture
def fake_erase(monkeypatch):
    calls: list[str] = []
    report = {
        "conversations": 2,
        "messages": 5,
        "attachments": 1,
        "files": 1,
        "vectors": 3,
        "failed": [],
    }

    async def _erase(history, sub):
        calls.append(sub)
        return dict(report)

    monkeypatch.setattr(erasure, "erase_subject", _erase)
    _erase.calls = calls
    _erase.report = report
    return _erase


def with_scope(tokens, user_id, scope, **kwargs):
    headers = tokens.issue(user_id, **kwargs)
    tokens.claims[headers["x-auth-request-access-token"]]["scope"] = scope
    return headers


# @verifies REQ-0057
async def test_a_token_with_the_erase_scope_erases_and_gets_the_counts(
    client, tokens, fake_erase
):
    headers = with_scope(tokens, ERASER, "profile assistant.subject.erase email")

    r = await client.post("/admin/subjects/erase", headers=headers, json={"sub": VICTIM})

    assert r.status_code == 200
    assert r.json() == {"sub": VICTIM, **fake_erase.report}
    assert fake_erase.calls == [VICTIM]


@pytest.mark.parametrize(
    "who",
    ["member", "platform_admin", "other_scope", "header_identity"],
)
# @verifies REQ-0057
async def test_anyone_without_the_scope_is_refused(
    client, tokens, user_headers, fake_erase, who
):
    headers = {
        "member": lambda: tokens.issue(USER_ID),
        "platform_admin": lambda: tokens.issue(ADMIN_ID, roles=(PLATFORM_ADMIN,)),
        "other_scope": lambda: with_scope(tokens, ERASER, "assistant.subject.read"),
        "header_identity": lambda: user_headers,
    }[who]()

    r = await client.post("/admin/subjects/erase", headers=headers, json={"sub": VICTIM})

    assert r.status_code == 403
    assert fake_erase.calls == []


# @verifies REQ-0057
async def test_a_scope_claim_given_as_a_list_counts(client, tokens, fake_erase):
    headers = with_scope(tokens, ERASER, ["assistant.subject.erase"])

    r = await client.post("/admin/subjects/erase", headers=headers, json={"sub": VICTIM})

    assert r.status_code == 200


@pytest.mark.parametrize("body", [{}, {"sub": ""}, {"sub": "   "}])
# @verifies REQ-0057
async def test_a_missing_subject_is_refused(client, tokens, fake_erase, body):
    headers = with_scope(tokens, ERASER, "assistant.subject.erase")

    r = await client.post("/admin/subjects/erase", headers=headers, json=body)

    assert r.status_code == 422
    assert fake_erase.calls == []


# @verifies REQ-0057
async def test_a_partial_erasure_is_503_with_the_report(client, tokens, fake_erase):
    fake_erase.report["failed"] = ["att-1"]
    headers = with_scope(tokens, ERASER, "assistant.subject.erase")

    r = await client.post("/admin/subjects/erase", headers=headers, json={"sub": VICTIM})

    assert r.status_code == 503
    assert r.json()["failed"] == ["att-1"]


# @verifies REQ-0057
async def test_the_log_names_the_caller_not_the_subject(client, tokens, fake_erase, caplog):
    headers = with_scope(tokens, ERASER, "assistant.subject.erase")

    with caplog.at_level(logging.INFO):
        await client.post("/admin/subjects/erase", headers=headers, json={"sub": VICTIM})

    logged = " ".join(
        f"{r.getMessage()} {r.__dict__}" for r in caplog.records if r.name.startswith("celine")
    )
    assert "subject_erased" in logged
    assert ERASER in logged
    assert VICTIM not in logged
