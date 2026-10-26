"""`celine-assistant erase-subject`, `retention run` and `kb orphans`: arguments, output
and exit codes. What they do is tested in `test_erasure.py`."""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from celine.assistant import cli, erasure
from tests.conftest import FakeHistoryStore, FakeKbStore

runner = CliRunner()


@pytest.fixture
def stores(monkeypatch):
    history, kb_store = FakeHistoryStore(), FakeKbStore()
    monkeypatch.setattr(cli, "HistoryStore", lambda: history)
    monkeypatch.setattr(cli, "KbStore", lambda: kb_store)
    monkeypatch.setattr(cli, "configure_logging", lambda level: None)
    return history


class Calls(list):
    """What the commands called, and what the next call reports as failed."""

    outcome: dict


@pytest.fixture
def calls(monkeypatch):
    seen = Calls()
    outcome = {"failed": []}

    async def _erase(history, sub):
        seen.append(("erase", sub))
        return {"conversations": 1, "failed": list(outcome["failed"])}

    async def _retention(history, *, months=None, now=None, dry_run=False):
        if months is not None and months < 1:
            raise ValueError("at least one month")
        seen.append(("retention", months, dry_run))
        return {"cutoff": "x", "dry_run": dry_run, "failed": list(outcome["failed"])}

    async def _orphans(history, *, delete=False):
        seen.append(("orphans", delete))
        return {"orphans": {}, "vectors": 0, "deleted": 0}

    monkeypatch.setattr(erasure, "erase_subject", _erase)
    monkeypatch.setattr(erasure, "run_retention", _retention)
    monkeypatch.setattr(erasure, "orphan_vectors", _orphans)
    seen.outcome = outcome
    return seen


def invoke(*args: str, input: str | None = None):
    result = runner.invoke(cli.app, list(args), input=input)
    body = None
    start = result.stdout.find("\n{") + 1 if not result.stdout.startswith("{") else 0
    if result.exit_code in (0, 1) and result.stdout[start:].startswith("{"):
        body = json.loads(result.stdout[start:])
    return result, body


# @verifies REQ-0057
def test_erase_subject_asks_first_and_prints_the_counts(stores, calls):
    result, body = invoke("erase-subject", "sub-1", input="y\n")

    assert result.exit_code == 0, result.output
    assert calls == [("erase", "sub-1")]
    assert body["conversations"] == 1


# @verifies REQ-0057
def test_erase_subject_does_nothing_when_not_confirmed(stores, calls):
    result, _ = invoke("erase-subject", "sub-1", input="n\n")

    assert result.exit_code != 0
    assert calls == []


# @verifies REQ-0057
def test_erase_subject_with_yes_does_not_ask(stores, calls):
    result, body = invoke("erase-subject", "sub-1", "--yes")

    assert result.exit_code == 0, result.output
    assert body == {"sub": "sub-1", "conversations": 1, "failed": []}


# @verifies REQ-0057
def test_a_partial_erasure_exits_1(stores, calls):
    calls.outcome["failed"] = ["att-1"]

    result, body = invoke("erase-subject", "sub-1", "--yes")

    assert result.exit_code == 1
    assert body["failed"] == ["att-1"]


# @verifies REQ-0058
def test_retention_run_passes_the_period_and_dry_run(stores, calls):
    result, body = invoke("retention", "run", "--months", "18", "--dry-run")

    assert result.exit_code == 0, result.output
    assert calls == [("retention", 18, True)]
    assert body["dry_run"] is True


# @verifies REQ-0058
def test_retention_run_uses_the_setting_by_default(stores, calls):
    result, _ = invoke("retention", "run")

    assert result.exit_code == 0, result.output
    assert calls == [("retention", None, False)]


# @verifies REQ-0058
def test_retention_run_refuses_a_period_under_a_month(stores, calls):
    result, _ = invoke("retention", "run", "--months", "0")

    assert result.exit_code not in (0, 1)
    assert calls == []


# @verifies REQ-0058
def test_retention_with_a_failure_exits_1(stores, calls):
    calls.outcome["failed"] = ["att-1"]

    result, _ = invoke("retention", "run")

    assert result.exit_code == 1


# @verifies REQ-0059
def test_kb_orphans_lists_and_deletes_on_request(stores, calls):
    assert invoke("kb", "orphans")[0].exit_code == 0
    assert invoke("kb", "orphans", "--delete")[0].exit_code == 0

    assert calls == [("orphans", False), ("orphans", True)]
