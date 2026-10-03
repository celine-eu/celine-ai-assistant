"""Administrator routes, and the starter prompts the UI asks for on load."""

from __future__ import annotations

import pytest

from celine.assistant import routes as routes_module
from tests.conftest import COMMUNITY, OTHER_COMMUNITY


# --- knowledge source sync -------------------------------------------------


@pytest.fixture
def fake_sync(monkeypatch):
    calls: list[dict] = []

    async def _sync_all(*, kb_store, community_id=None, full=False):
        calls.append({"community_id": community_id, "full": full})
        return [{"source_id": "s1", "indexed": 3}]

    monkeypatch.setattr(routes_module.kb_sources, "sync_all", _sync_all)
    return calls


# @verifies REQ-0005
async def test_a_sync_is_for_managers_only(client, member_headers, fake_sync):
    r = await client.post("/admin/kb/sync", headers=member_headers, json={})

    assert r.status_code == 403
    assert fake_sync == []


# @verifies REQ-0033
async def test_a_manager_syncs_their_own_community(client, manager_headers, fake_sync):
    r = await client.post("/admin/kb/sync", headers=manager_headers, json={"full": True})

    assert r.status_code == 200
    assert r.json()["community_id"] == COMMUNITY
    assert r.json()["sources"][0]["indexed"] == 3
    assert fake_sync == [{"community_id": COMMUNITY, "full": True}]


# @verifies REQ-0005
async def test_a_manager_cannot_sync_another_community(client, manager_headers, fake_sync):
    r = await client.post(
        "/admin/kb/sync", headers=manager_headers, json={"community_id": OTHER_COMMUNITY}
    )

    assert r.status_code == 403
    assert fake_sync == []


# @verifies REQ-0033
async def test_a_realm_administrator_names_the_community_to_sync(
    client, admin_headers, fake_sync
):
    assert (await client.post("/admin/kb/sync", headers=admin_headers, json={})).status_code == 400

    r = await client.post(
        "/admin/kb/sync", headers=admin_headers, json={"community_id": OTHER_COMMUNITY}
    )
    assert r.status_code == 200
    assert fake_sync == [{"community_id": OTHER_COMMUNITY, "full": False}]


async def test_the_error_boundary_hides_the_detail_of_an_unexpected_failure(
    client, manager_headers, monkeypatch
):
    """Whatever went wrong upstream, the caller is told "Internal Server Error" and the
    traceback goes to the log. The middleware in `main.py` is what guarantees it.

    @verifies REQ-0034
    """

    async def _explode(*, kb_store, community_id=None, full=False):
        raise OSError("/mnt/secrets/token is unreadable")

    monkeypatch.setattr(routes_module.kb_sources, "sync_all", _explode)

    r = await client.post("/admin/kb/sync", headers=manager_headers, json={})

    assert r.status_code == 500
    assert r.json() == {"detail": "Internal Server Error"}


# --- suggestions ------------------------------------------------------------


# @verifies REQ-0029
async def test_suggestions_are_returned_with_their_tool_labels(
    client, user_headers, forwarded_token
):
    body = (await client.get("/suggestions", headers=forwarded_token())).json()

    assert body["suggestions"]
    assert body["tool_labels"]["search_documents"] == "Searching documents"


# @verifies REQ-0029
async def test_suggestions_are_translated(client, user_headers):
    body = (await client.get("/suggestions?lang=it", headers=user_headers)).json()

    assert body["tool_labels"]["search_documents"] == "Ricerca nei documenti"


async def test_a_caller_with_no_forwarded_token_still_gets_prompts(
    client, user_headers
):
    """Every *upstream* skill needs a forwarded access token, so a deployment where the
    proxy passes identity headers and not the token registers only the documents skill.
    At least one starter prompt has to name that skill, or the UI opens empty.

    @verifies REQ-0029
    """
    body = (await client.get("/suggestions", headers=user_headers)).json()

    assert body["suggestions"]
    assert "What can you help me with?" in [s["text"] for s in body["suggestions"]]


# @verifies REQ-0029
async def test_a_verified_token_adds_the_upstream_prompts(
    client, user_headers, forwarded_token
):
    without = (await client.get("/suggestions", headers=user_headers)).json()
    with_token = (await client.get("/suggestions", headers=forwarded_token())).json()

    assert len(with_token["suggestions"]) > len(without["suggestions"])
    assert all({"text", "icon"} == set(s) for s in with_token["suggestions"])
