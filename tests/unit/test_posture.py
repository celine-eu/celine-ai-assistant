"""Development values are refused anywhere but dev, and dev is said explicitly.

The signal is `CELINE_ENV`, then `ENVIRONMENT`, then the legacy `APP_ENV`; only `dev`
relaxes. Until this was in place the flag was `APP_ENV` with a `prod` default compared
by `!=`, so `APP_ENV=production` or `staging` served wildcard CORS with credentials.
"""

from __future__ import annotations

import logging

import pytest
from celine.sdk.posture import InsecureConfiguration
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient

from celine.assistant import main as main_module
from celine.assistant import posture
from celine.assistant.auth import get_user_identity
from celine.assistant.settings import Settings, settings
from tests.unit.test_auth import make_request

ENV_VARS = ("CELINE_ENV", "ENVIRONMENT", "APP_ENV")

DEPLOYED = {
    "DATABASE_URL": "postgresql+asyncpg://assistant:9b3e1f7a@db.rec.example.org:5432/assistant",
    "OAUTH2_TRUST_HEADERS": False,
    "OAUTH2_ISSUER": "https://auth.rec.example.org/realms/example-rec",
    "OAUTH2_JWKS_URL": "https://auth.rec.example.org/realms/example-rec/certs",
    "QDRANT_API_KEY": "a-qdrant-key",
}

DEV_VALUES = [
    ({"DATABASE_URL": "postgresql+asyncpg://postgres:securepassword123@db:5432/x"}, "DATABASE_URL"),
    ({"OAUTH2_TRUST_HEADERS": True}, "OAUTH2_TRUST_HEADERS"),
    ({"OAUTH2_ISSUER": None}, "OAUTH2_ISSUER"),
    ({"QDRANT_API_KEY": None}, "QDRANT_API_KEY"),
]


def _settings(**overrides) -> Settings:
    # No env file: the checkout's `.env` must not decide what is being tested.
    return Settings(_env_file=None, **{**DEPLOYED, **overrides})


@pytest.fixture
def no_signal(monkeypatch):
    for name in ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


# --- the guard ---------------------------------------------------------------


# @verifies REQ-0045
@pytest.mark.parametrize("env", ["", "staging", "prod", "production"])
def test_a_deployed_configuration_starts_hardened(env):
    posture.enforce_posture(_settings(), env=env)


# @verifies REQ-0045
@pytest.mark.parametrize("env", ["", "staging"])
@pytest.mark.parametrize(("override", "setting"), DEV_VALUES)
def test_each_development_value_is_refused_outside_dev(env, override, setting):
    with pytest.raises(InsecureConfiguration, match=setting):
        posture.enforce_posture(_settings(**override), env=env)


# @verifies REQ-0045
@pytest.mark.parametrize(("override", "setting"), DEV_VALUES)
def test_dev_warns_and_starts(override, setting, caplog):
    with caplog.at_level(logging.WARNING, logger="celine.sdk.posture"):
        posture.enforce_posture(_settings(**override), env="dev")
    assert setting in caplog.text


# --- the signal --------------------------------------------------------------


# @verifies REQ-0045
def test_unset_is_hardened_whatever_the_old_default_says(no_signal):
    s = Settings(_env_file=None)
    assert s.app_env == "prod"  # the field's default is not a signal
    assert posture.current_env(s) == ""
    assert not posture.is_dev(s)


# @verifies REQ-0045
def test_app_env_is_still_read_after_celine_env_and_environment(no_signal):
    no_signal.setenv("APP_ENV", "dev")
    assert posture.is_dev(Settings(_env_file=None))

    no_signal.setenv("ENVIRONMENT", "staging")
    assert not posture.is_dev(Settings(_env_file=None))

    no_signal.setenv("CELINE_ENV", "dev")
    assert posture.is_dev(Settings(_env_file=None))


# @verifies REQ-0045
def test_an_app_env_from_the_env_file_is_the_last_fallback(no_signal):
    assert posture.is_dev(Settings(_env_file=None, APP_ENV="dev"))
    no_signal.setenv("CELINE_ENV", "staging")
    assert not posture.is_dev(Settings(_env_file=None, APP_ENV="dev"))


# --- startup -----------------------------------------------------------------


# @verifies REQ-0045
@pytest.mark.parametrize("env", ["", "staging"])
async def test_header_trust_refuses_startup_before_anything_is_reached(
    env, no_signal, monkeypatch
):
    """Hardened, with header trust on: startup stops before Qdrant is asked."""
    no_signal.setenv("CELINE_ENV", env)
    for name, value in DEPLOYED.items():
        monkeypatch.setattr(settings, name.lower(), value)
    monkeypatch.setattr(settings, "oauth2_trust_headers", True)

    reached = []
    monkeypatch.setattr(main_module.kb_collections, "qdrant_client", lambda: reached.append(1))

    with pytest.raises(InsecureConfiguration, match="OAUTH2_TRUST_HEADERS"):
        async with main_module.lifespan(FastAPI()):
            pass
    assert not reached


# --- what header trust off means for a spoofed caller -------------------------


# @verifies REQ-0001
# @verifies REQ-0003
async def test_spoofed_admin_headers_without_a_token_are_401(monkeypatch):
    """With header trust off — the only setting a hardened deployment starts with —
    `X-Auth-Request-Groups: admins` and no token is no identity at all."""
    monkeypatch.setattr(settings, "oauth2_trust_headers", False)
    spoofed = {
        "x-auth-request-user": "mallory",
        "x-auth-request-email": "mallory@example.org",
        "x-auth-request-groups": "admins",
    }
    with pytest.raises(HTTPException) as exc:
        await get_user_identity(make_request(spoofed))
    assert exc.value.status_code == 401


# @verifies REQ-0001
# @verifies REQ-0003
async def test_spoofed_admin_headers_are_refused_by_an_admin_route(app, monkeypatch):
    monkeypatch.setattr(settings, "oauth2_trust_headers", False)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post(
            "/admin/kb/sync",
            headers={"x-auth-request-user": "mallory", "x-auth-request-groups": "admins"},
            json={"community_id": "example-rec"},
        )
    assert r.status_code == 401


# --- CORS ----------------------------------------------------------------------


def _cors_origins(application) -> list[str]:
    for middleware in application.user_middleware:
        if middleware.cls.__name__ == "CORSMiddleware":
            return middleware.kwargs["allow_origins"]
    raise AssertionError("no CORS middleware")


# @verifies REQ-0046
@pytest.mark.parametrize(
    ("variables", "wildcard"),
    [
        ({"CELINE_ENV": "dev"}, True),
        ({"APP_ENV": "dev"}, True),
        ({}, False),
        ({"APP_ENV": "production"}, False),
        ({"APP_ENV": "staging"}, False),
        ({"CELINE_ENV": "staging", "APP_ENV": "dev"}, False),
        ({"ENVIRONMENT": "prod"}, False),
    ],
)
def test_wildcard_cors_is_for_dev_only(no_signal, monkeypatch, variables, wildcard):
    for name, value in variables.items():
        no_signal.setenv(name, value)
    # Only the process environment decides here, not an APP_ENV the checkout's .env set.
    monkeypatch.setattr(posture, "settings", Settings(_env_file=None))
    origins = _cors_origins(main_module.create_app())
    assert (origins == ["*"]) is wildcard
    if not wildcard:
        assert origins == []
