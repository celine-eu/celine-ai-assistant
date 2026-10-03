"""Development or not: the one signal every relaxation here is decided by.

The platform rule (`celine.sdk.posture`): **only `dev` relaxes**. The signal is
`CELINE_ENV`, then `ENVIRONMENT`, then this service's own `APP_ENV`; the first
non-empty one wins. Unset, empty, `prod`, `production`, `staging`, `test` or a typo
is hardened. `APP_ENV` is still accepted — from the environment or from `.env` —
but it no longer has a default that decides anything: its old `prod` default was
compared with `!=`, so `production` or `staging` silently got wildcard CORS.

At startup `enforce_posture` refuses, outside dev, every value that is safe only
on a developer's machine; in dev it logs them as one warning.

TODO: `celine.sdk.posture` is not in a released celine-sdk yet. Raise the
`celine-sdk` floor in pyproject.toml to the first release that ships it; until
then this needs the local SDK checkout installed editable.
"""

from __future__ import annotations

from celine.sdk.posture import DEV, PostureGuard
from celine.sdk.posture import current_env as _sdk_current_env

from .settings import Settings, settings

SERVICE = "celine-ai-assistant"
LEGACY_ENV_VAR = "APP_ENV"


def current_env(s: Settings | None = None) -> str:
    """The environment signal, lowercased; ``""`` when nothing states one.

    The process environment first (`CELINE_ENV`, `ENVIRONMENT`, `APP_ENV`), then an
    `APP_ENV` that `.env` set explicitly. The field's own default is not a signal.
    """
    env = _sdk_current_env(LEGACY_ENV_VAR)
    if env:
        return env
    s = s or settings
    if "app_env" in s.model_fields_set and s.app_env.strip():
        return s.app_env.strip().lower()
    return ""


def is_dev(s: Settings | None = None) -> bool:
    return current_env(s) == DEV


def posture_guard(s: Settings | None = None, env: str | None = None) -> PostureGuard:
    """A guard holding every development-only value `s` carries.

    ``env`` overrides the signal, for tests.
    """
    s = s or settings
    guard = PostureGuard(SERVICE, env=current_env(s) if env is None else env)

    guard.forbid_dev_database_url("DATABASE_URL", s.database_url)
    guard.forbid_true(
        "OAUTH2_TRUST_HEADERS",
        s.oauth2_trust_headers,
        "Unset it. It turns unverified X-Auth-Request-* headers, groups included, "
        "into an identity; outside dev every caller must present a verified token.",
    )
    guard.require_set(
        "OAUTH2_ISSUER",
        s.oauth2_issuer,
        "Set it to the realm's issuer. With OAUTH2_JWKS_URL alone the token's `iss` "
        "is not checked, so any issuer sharing that key set is accepted.",
    )
    guard.require_set(
        "QDRANT_API_KEY",
        s.qdrant_api_key,
        "Set the Qdrant API key: the knowledge bases of every community are in it.",
    )
    return guard


def enforce_posture(s: Settings | None = None, env: str | None = None) -> None:
    """Refuse to start outside dev with any development-only value; warn in dev."""
    posture_guard(s, env=env).enforce()
