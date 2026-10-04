"""Real Keycloak tokens through the real verification and the real app.

Everything else in this suite fakes the signature check (`tokens` in `conftest.py`) and
so believes whatever claims a test writes. These tests do not: they take access tokens
from a running Keycloak, verify them against its published key set (discovery from the
configured issuer, signature, `iss`, `aud`), and ask the app what the caller may do.
What they prove is that the claim shapes Keycloak really emits meet the two-level model
(REQ-0004): the `platform-admin` realm role is the only platform grant, an
organization's `admins` group is valid only in that organization, and a realm group still
present in a token grants nothing.

Opt-in, because they need a Keycloak and the default run needs no network:

    KEYCLOAK_IT_ISSUER=http://keycloak.celine.localhost/realms/celine \\
        uv run pytest tests/integration

| Variable | Default | |
|---|---|---|
| `KEYCLOAK_IT_ISSUER` | — (skip) | realm URL; tokens must carry it as `iss` |
| `KEYCLOAK_IT_CLIENT_ID` | `oauth2_proxy` | the user-token client |
| `KEYCLOAK_IT_CLIENT_SECRET` | `oauth2_proxy` | its secret (the local dev value) |
| `KEYCLOAK_IT_PLATFORM_ADMIN` | `admin` | a user holding `platform-admin`; password = username |
| `KEYCLOAK_IT_ORG_ADMIN` | `org-admin` | a user in one REC's `admins` group, no realm role |
| `KEYCLOAK_IT_ORG_VIEWER` | `org-viewer` | a user in the same REC's `viewers` group |
| `KEYCLOAK_IT_REC` | `example_rec` | that REC's organization alias |
| `KEYCLOAK_IT_LEGACY_TOKEN` | — (skip that test) | an access token still carrying the realm group `/admins` and the retired realm role `admin`, minted for the purpose; the realm itself no longer issues one |

Local stack only. Never point these at a shared environment.
"""

from __future__ import annotations

import base64
import json
import os
from typing import Any

import httpx
import pytest

from celine.assistant import auth as auth_module
from celine.assistant import routes as routes_module
from celine.assistant.settings import settings

ISSUER = os.environ.get("KEYCLOAK_IT_ISSUER", "").rstrip("/")
CLIENT_ID = os.environ.get("KEYCLOAK_IT_CLIENT_ID", "oauth2_proxy")
CLIENT_SECRET = os.environ.get("KEYCLOAK_IT_CLIENT_SECRET", "oauth2_proxy")
PLATFORM_ADMIN_USER = os.environ.get("KEYCLOAK_IT_PLATFORM_ADMIN", "admin")
ORG_ADMIN_USER = os.environ.get("KEYCLOAK_IT_ORG_ADMIN", "org-admin")
ORG_VIEWER_USER = os.environ.get("KEYCLOAK_IT_ORG_VIEWER", "org-viewer")
REC = os.environ.get("KEYCLOAK_IT_REC", "example_rec")
LEGACY_TOKEN = os.environ.get("KEYCLOAK_IT_LEGACY_TOKEN", "")
OTHER_REC = "other-rec"

pytestmark = pytest.mark.skipif(
    not ISSUER, reason="set KEYCLOAK_IT_ISSUER to run against a local Keycloak"
)


def _claims(token: str) -> dict[str, Any]:
    payload = token.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))


def _user_token(username: str) -> str:
    r = httpx.post(
        f"{ISSUER}/protocol/openid-connect/token",
        data={
            "grant_type": "password",
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "username": username,
            "password": username,
            # What oauth2-proxy requests: `organization:*` lists every organization of
            # a multi-organization user.
            "scope": "openid email profile organization:*",
        },
        timeout=10.0,
    )
    r.raise_for_status()
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def real_tokens() -> dict[str, str]:
    return {
        "platform_admin": _user_token(PLATFORM_ADMIN_USER),
        "org_admin": _user_token(ORG_ADMIN_USER),
        "org_viewer": _user_token(ORG_VIEWER_USER),
    }


@pytest.fixture(autouse=True)
def verify_against_the_realm(monkeypatch):
    """The production path: discovery from the configured issuer, nothing faked, and
    no header identity to fall back to."""
    monkeypatch.setattr(settings, "oauth2_issuer", ISSUER)
    monkeypatch.setattr(settings, "oauth2_jwks_url", None)
    monkeypatch.setattr(settings, "oauth2_audience", CLIENT_ID)
    monkeypatch.setattr(settings, "oauth2_trust_headers", False)
    monkeypatch.setattr(auth_module, "_discovery_cache", {})
    monkeypatch.setattr(auth_module, "_jwks_cache", {})


@pytest.fixture
def fake_sync(monkeypatch):
    calls: list[dict] = []

    async def _sync_all(*, kb_store, community_id=None, full=False):
        calls.append({"community_id": community_id, "full": full})
        return []

    monkeypatch.setattr(routes_module.kb_sources, "sync_all", _sync_all)
    return calls


def bearer(token: str) -> dict[str, str]:
    return {"authorization": f"Bearer {token}"}


async def test_the_platform_admin_role_holder_is_a_platform_administrator(
    client, real_tokens, fake_sync
):
    """@verifies REQ-0004 @verifies REQ-0005"""
    token = real_tokens["platform_admin"]
    assert "platform-admin" in _claims(token)["realm_access"]["roles"]

    body = (await client.get("/user", headers=bearer(token))).json()
    assert body["is_platform_admin"] is True
    assert body["is_admin"] is True
    assert "platform-admin" in body["roles"]

    r = await client.post(
        "/admin/kb/sync", headers=bearer(token), json={"community_id": OTHER_REC}
    )
    assert r.status_code == 200
    assert fake_sync == [{"community_id": OTHER_REC, "full": False}]


async def test_an_organization_admins_member_is_not_a_platform_administrator(
    client, real_tokens, fake_sync
):
    """`admins` inside one REC manages that REC and nothing else.

    @verifies REQ-0004 @verifies REQ-0005
    """
    token = real_tokens["org_admin"]
    claims = _claims(token)
    assert "platform-admin" not in claims.get("realm_access", {}).get("roles", [])
    assert claims["organization"][REC]["groups"] == ["/admins"]

    body = (await client.get("/user", headers=bearer(token))).json()
    assert body["is_platform_admin"] is False
    assert "platform-admin" not in body["roles"]
    assert body["community_id"] == REC
    # A manager of their own community, which is what the UI gates on.
    assert body["is_admin"] is True

    other = await client.post(
        "/admin/kb/sync", headers=bearer(token), json={"community_id": OTHER_REC}
    )
    assert other.status_code == 403
    own = await client.post("/admin/kb/sync", headers=bearer(token), json={})
    assert own.status_code == 200
    assert fake_sync == [{"community_id": REC, "full": False}]


async def test_an_organization_viewer_administers_nothing(client, real_tokens, fake_sync):
    """@verifies REQ-0004 @verifies REQ-0005"""
    token = real_tokens["org_viewer"]

    body = (await client.get("/user", headers=bearer(token))).json()
    assert body["is_platform_admin"] is False
    assert body["is_admin"] is False
    assert body["community_id"] == REC

    r = await client.post("/admin/kb/sync", headers=bearer(token), json={})
    assert r.status_code == 403
    assert fake_sync == []


@pytest.mark.skipif(
    not LEGACY_TOKEN, reason="set KEYCLOAK_IT_LEGACY_TOKEN to a token carrying /admins"
)
async def test_a_realm_group_still_in_a_token_grants_nothing(client, fake_sync):
    """The token verifies — it is the realm's own signature — and still carries the
    realm group `/admins` in both forms and the retired realm role `admin`. Neither is
    a platform grant.

    @verifies REQ-0004
    """
    claims = _claims(LEGACY_TOKEN)
    assert "/admins" in claims.get("groups", []) or "admins" in claims.get("groups", [])
    assert "platform-admin" not in claims.get("realm_access", {}).get("roles", [])

    r = await client.get("/user", headers=bearer(LEGACY_TOKEN))
    assert r.status_code == 200, "the legacy token must verify, or this proves nothing"
    body = r.json()
    assert body["is_platform_admin"] is False
    assert "platform-admin" not in body["roles"]

    other = await client.post(
        "/admin/kb/sync", headers=bearer(LEGACY_TOKEN), json={"community_id": OTHER_REC}
    )
    assert other.status_code == 403
    assert fake_sync == []


async def test_a_forged_role_does_not_verify(client, real_tokens):
    """The same token with `platform-admin` written into it is refused: the role is
    only as good as the signature that carries it.

    @verifies REQ-0002 @verifies REQ-0004
    """
    header, _payload, signature = real_tokens["org_admin"].split(".")
    claims = _claims(real_tokens["org_admin"])
    claims["realm_access"] = {"roles": ["platform-admin"]}
    forged_payload = (
        base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=").decode()
    )
    forged = f"{header}.{forged_payload}.{signature}"

    r = await client.get("/user", headers=bearer(forged))
    assert r.status_code == 401
