"""Administrator routes, and the starter prompts the UI asks for on load."""

from __future__ import annotations

import pytest

from celine.assistant import routes as routes_module


# --- training material sync -------------------------------------------------


@pytest.fixture
def fake_sync(monkeypatch):
    calls: list[dict] = []

    async def _sync(*, target_ref, force_full=False):
        calls.append({"target_ref": target_ref, "force_full": force_full})
        if isinstance(calls[-1].get("raises"), Exception):  # pragma: no cover
            raise calls[-1]["raises"]
        return {"status": "ok", "git": {"updated": True}, "ingest": {"indexed": 3}}

    monkeypatch.setattr(routes_module, "sync_training_materials", _sync)
    return calls


# @verifies REQ-0005
async def test_a_sync_is_administrator_only(client, user_headers, fake_sync):
    r = await client.post(
        "/admin/training-materials/sync", headers=user_headers, json={}
    )

    assert r.status_code == 403
    assert fake_sync == []


# @verifies REQ-0033
async def test_an_administrator_can_sync_to_a_named_ref(
    client, admin_headers, fake_sync
):
    r = await client.post(
        "/admin/training-materials/sync",
        headers=admin_headers,
        json={"target_ref": "v2.1.0"},
    )

    assert r.status_code == 200
    assert r.json()["ingest"]["indexed"] == 3
    assert fake_sync == [{"target_ref": "v2.1.0", "force_full": False}]


# @verifies REQ-0033
async def test_a_sync_without_a_ref_uses_the_configured_default(
    client, admin_headers, fake_sync
):
    await client.post("/admin/training-materials/sync", headers=admin_headers, json={})
    assert fake_sync[0]["target_ref"] is None


async def test_a_refused_sync_is_a_conflict_not_a_server_error(
    client, admin_headers, monkeypatch
):
    """A dirty checkout is the operator's problem to clear, and 409 is what says so.
    Anything else this raises is still a 500.

    @verifies REQ-0033
    """

    async def _refuse(*, target_ref, force_full=False):
        raise RuntimeError("Training materials repo has local changes; refusing sync")

    monkeypatch.setattr(routes_module, "sync_training_materials", _refuse)

    r = await client.post(
        "/admin/training-materials/sync", headers=admin_headers, json={}
    )

    assert r.status_code == 409
    assert "local changes" in r.json()["detail"]


# @verifies REQ-0033
async def test_an_unexpected_sync_failure_is_a_server_error(
    client, admin_headers, monkeypatch
):

    async def _explode(*, target_ref, force_full=False):
        raise OSError("disk full")

    monkeypatch.setattr(routes_module, "sync_training_materials", _explode)

    r = await client.post(
        "/admin/training-materials/sync", headers=admin_headers, json={}
    )
    assert r.status_code == 500


async def test_the_error_boundary_hides_the_detail_of_an_unexpected_failure(
    client, admin_headers, monkeypatch
):
    """Whatever went wrong upstream, the caller is told "Internal Server Error" and the
    traceback goes to the log. The middleware in `main.py` is what guarantees it.

    @verifies REQ-0034
    """

    async def _explode(*, target_ref, force_full=False):
        raise OSError("/mnt/secrets/token is unreadable")

    monkeypatch.setattr(routes_module, "sync_training_materials", _explode)

    r = await client.post(
        "/admin/training-materials/sync", headers=admin_headers, json={}
    )

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
