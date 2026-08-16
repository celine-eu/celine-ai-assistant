"""Identity extraction, as the code does it today.

Nothing here verifies a signature: `_verify_jwt` is `python-jose` and the JWKS fetch is
`httpx`, both outside this repository. What is ours — and what these pin — is the order
the token is looked for in, the trusted-header path, and what happens when verification
fails.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from celine.assistant.auth import (
    UserIdentity,
    UserInfo,
    extract_access_token,
    get_user_identity,
    is_admin,
)
from celine.assistant.settings import settings


def make_request(
    headers: dict[str, str] | None = None, cookies: dict[str, str] | None = None
) -> Request:
    raw = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    if cookies:
        raw.append(
            (b"cookie", "; ".join(f"{k}={v}" for k, v in cookies.items()).encode())
        )
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "raw_path": b"/",
            "query_string": b"",
            "headers": raw,
            "scheme": "http",
            "server": ("test", 80),
            "client": ("test", 1234),
        }
    )


# --- token extraction order -------------------------------------------------


# @verifies REQ-0002
def test_oauth2_proxy_header_wins_over_authorization():
    req = make_request(
        {
            "x-auth-request-access-token": "from-proxy",
            "authorization": "Bearer from-authorization",
        }
    )
    assert extract_access_token(req) == "from-proxy"


# @verifies REQ-0002
def test_authorization_bearer_is_the_second_choice():
    req = make_request({"authorization": "Bearer from-authorization"})
    assert extract_access_token(req) == "from-authorization"


# @verifies REQ-0002
def test_bearer_prefix_is_matched_case_insensitively():
    assert extract_access_token(make_request({"authorization": "bearer tok"})) == "tok"
    assert extract_access_token(make_request({"authorization": "BEARER tok"})) == "tok"


# @verifies REQ-0002
def test_non_bearer_authorization_is_ignored():
    assert extract_access_token(make_request({"authorization": "Basic abc"})) is None


# @verifies REQ-0002
def test_cookie_is_the_last_choice_and_only_when_named(monkeypatch):
    monkeypatch.setattr(settings, "oauth2_jwt_cookie_name", None)
    assert extract_access_token(make_request(cookies={"session": "tok"})) is None

    monkeypatch.setattr(settings, "oauth2_jwt_cookie_name", "session")
    assert extract_access_token(make_request(cookies={"session": "tok"})) == "tok"


# @verifies REQ-0002
def test_no_token_anywhere():
    assert extract_access_token(make_request()) is None


# --- trusted headers --------------------------------------------------------


# @verifies REQ-0003
async def test_trusted_headers_produce_an_identity():
    req = make_request(
        {
            "x-auth-request-user": "alice",
            "x-auth-request-email": "alice@example.test",
            "x-auth-request-groups": "members, admins ,",
        }
    )
    identity = await get_user_identity(req)

    assert identity.user_id == "alice"
    assert identity.raw["source"] == "trusted-headers"
    # Blank entries are dropped and each name is stripped.
    assert identity.raw["claims"]["groups"] == ["members", "admins"]


# @verifies REQ-0003
async def test_email_header_alone_is_enough_to_identify():
    identity = await get_user_identity(
        make_request({"x-auth-request-email": "alice@example.test"})
    )
    assert identity.user_id == "alice@example.test"


# @verifies REQ-0001
async def test_no_identity_at_all_is_rejected():
    with pytest.raises(HTTPException) as exc:
        await get_user_identity(make_request())
    assert exc.value.status_code == 401


# @verifies REQ-0003
async def test_trusted_headers_are_ignored_when_the_switch_is_off(monkeypatch):
    monkeypatch.setattr(settings, "oauth2_trust_headers", False)
    with pytest.raises(HTTPException) as exc:
        await get_user_identity(make_request({"x-auth-request-user": "alice"}))
    assert exc.value.status_code == 401


async def test_a_token_that_does_not_verify_is_refused_even_with_headers_present():
    """A presented token must verify. It is not downgraded to header trust.

    The headers are only an identity for a request that carries no token at all —
    otherwise an expired or forged token would be indistinguishable from no token, and
    with `OAUTH2_TRUST_HEADERS` on that is whatever identity the caller asserted.

    @verifies REQ-0002
    """
    req = make_request(
        {
            "authorization": "Bearer not-a-real-jwt",
            "x-auth-request-user": "alice",
        }
    )

    with pytest.raises(HTTPException) as exc:
        await get_user_identity(req)

    assert exc.value.status_code == 401
    assert "JWT verification failed" in exc.value.detail


# @verifies REQ-0001
async def test_an_unverifiable_token_with_no_headers_is_rejected():
    with pytest.raises(HTTPException) as exc:
        await get_user_identity(make_request({"authorization": "Bearer nonsense"}))
    assert exc.value.status_code == 401


# --- admin ------------------------------------------------------------------


def identity_with_groups(*groups: str) -> UserIdentity:
    return UserIdentity(
        user_id="u", raw={"source": "test", "claims": {"groups": list(groups)}}
    )


# @verifies REQ-0004
def test_admin_is_group_membership():
    assert is_admin(identity_with_groups("members", settings.admin_group))
    assert not is_admin(identity_with_groups("members"))
    assert not is_admin(UserIdentity(user_id="u", raw={}))


def test_admin_group_is_matched_with_the_leading_slash_stripped():
    """Keycloak emits `/admins`; `extract_groups` normalises it. @verifies REQ-0004"""
    assert is_admin(identity_with_groups(f"/{settings.admin_group}"))


# @verifies REQ-0004
def test_org_scoped_groups_also_confer_admin():
    identity = UserIdentity(
        user_id="u",
        raw={
            "claims": {
                "organization": {"celine": {"groups": [settings.admin_group]}},
            }
        },
    )
    assert is_admin(identity)


# @verifies REQ-0004
def test_user_info_is_projected_from_the_claims():
    identity = UserIdentity(
        user_id="alice",
        raw={
            "claims": {
                "sub": "alice",
                "name": "Alice Example",
                "given_name": "Alice",
                "family_name": "Example",
                "email": "alice@example.test",
                "groups": ["members", settings.admin_group],
            }
        },
    )
    info = UserInfo.from_identity(identity)

    assert info.user_id == "alice"
    assert info.username == "alice"
    assert info.full_name == "Alice Example"
    assert info.first_name == "Alice"
    assert info.last_name == "Example"
    assert info.email == "alice@example.test"
    assert info.is_admin is True


# @verifies REQ-0004
def test_user_info_falls_back_to_preferred_username():
    identity = UserIdentity(
        user_id="alice", raw={"claims": {"preferred_username": "alice@corp"}}
    )
    assert UserInfo.from_identity(identity).username == "alice@corp"


# @verifies REQ-0004
def test_user_info_of_an_identity_with_no_claims_is_empty_but_not_an_error():
    info = UserInfo.from_identity(UserIdentity(user_id="alice", raw={}))
    assert info.user_id == "alice"
    assert info.username == ""
    assert info.groups == []
    assert info.is_admin is False
