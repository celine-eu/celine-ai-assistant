"""What is reachable without an identity, and what is not."""

from __future__ import annotations

import pytest


async def test_health_is_open(client):
    """The liveness probe runs before any proxy has attached headers.

    @verifies REQ-0001
    """
    r = await client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


# @verifies REQ-0001
async def test_ping_needs_an_identity(client):
    assert (await client.get("/ping")).status_code == 401


# @verifies REQ-0001
async def test_ping_answers_an_identified_caller(client, user_headers):
    r = await client.get("/ping", headers=user_headers)
    assert r.status_code == 200
    assert r.json() == {"ok": True}


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/ping"),
        ("get", "/user"),
        ("get", "/suggestions"),
        ("get", "/attachments"),
        ("get", "/conversations"),
        ("get", "/conversations/c1/messages"),
        ("delete", "/conversations/c1"),
        ("get", "/attachments/a1/raw"),
        ("delete", "/attachments/a1"),
        ("post", "/chat"),
        ("post", "/upload"),
        ("post", "/admin/uploads"),
        ("post", "/admin/training-materials/sync"),
    ],
)
# @verifies REQ-0001
async def test_every_other_route_rejects_an_anonymous_caller(client, method, path):
    r = await getattr(client, method)(path)
    assert r.status_code == 401, f"{method.upper()} {path} answered {r.status_code}"


# @verifies REQ-0004
async def test_the_user_route_projects_the_identity(client, user_headers):
    body = (await client.get("/user", headers=user_headers)).json()

    assert body["user_id"] == "alice"
    assert body["email"] == "alice@example.test"
    assert body["groups"] == ["members"]
    assert body["is_admin"] is False


# @verifies REQ-0004
async def test_an_admin_is_reported_as_one(client, admin_headers):
    body = (await client.get("/user", headers=admin_headers)).json()
    assert body["is_admin"] is True
