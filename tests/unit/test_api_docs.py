"""The interactive API docs and the schema are mounted only in development.

`celine.sdk.posture.docs_urls`, on the signal of REQ-0045 (`CELINE_ENV`, then
`ENVIRONMENT`, then the legacy `APP_ENV`): in dev `/docs`, `/redoc` and `/openapi.json`
are served; anywhere else, unset included, they are not mounted unless
`CELINE_PUBLIC_DOCS=true`.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from celine.assistant import main as main_module
from celine.assistant import posture
from celine.assistant.settings import Settings

PATHS = ("/docs", "/redoc", "/openapi.json")


def _client(monkeypatch, variables: dict[str, str]) -> TestClient:
    for name in ("CELINE_ENV", "ENVIRONMENT", "APP_ENV", "CELINE_PUBLIC_DOCS"):
        monkeypatch.delenv(name, raising=False)
    for name, value in variables.items():
        monkeypatch.setenv(name, value)
    # Only the process environment decides here, not an APP_ENV the checkout's .env set.
    monkeypatch.setattr(posture, "settings", Settings(_env_file=None))
    # No `with`: the lifespan (posture guard, Qdrant) is not under test here.
    return TestClient(main_module.create_app())


# @verifies REQ-0046
@pytest.mark.parametrize(
    "variables",
    [
        {},
        {"CELINE_ENV": "staging"},
        {"APP_ENV": "production"},
        {"CELINE_ENV": "staging", "APP_ENV": "dev"},
        {"CELINE_ENV": "staging", "CELINE_PUBLIC_DOCS": "false"},
    ],
)
def test_outside_dev_the_docs_are_not_mounted(monkeypatch, variables):
    client = _client(monkeypatch, variables)

    assert [client.get(p).status_code for p in PATHS] == [404, 404, 404]


# @verifies REQ-0046
def test_the_public_docs_opt_in_serves_them_outside_dev(monkeypatch):
    client = _client(
        monkeypatch, {"CELINE_ENV": "staging", "CELINE_PUBLIC_DOCS": "true"}
    )

    assert [client.get(p).status_code for p in PATHS] == [200, 200, 200]


# @verifies REQ-0046
@pytest.mark.parametrize("variables", [{"CELINE_ENV": "dev"}, {"APP_ENV": "dev"}])
def test_dev_serves_the_docs(monkeypatch, variables):
    client = _client(monkeypatch, variables)

    assert [client.get(p).status_code for p in PATHS] == [200, 200, 200]
    assert client.get("/openapi.json").json()["info"]["title"] == "CELINE Chatbot API"
