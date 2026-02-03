from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any

import httpx
from fastapi import Request
from jose import jwt

from .settings import settings

log = logging.getLogger(__name__)

_HTTP_TIMEOUT = 10.0
_DISCOVERY_TTL_SECONDS = 3600
_JWKS_TTL_SECONDS = 3600

_discovery_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_jwks_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_cache_lock = asyncio.Lock()


@dataclass(frozen=True)
class UserIdentity:
    user_id: str
    raw: dict[str, Any]


class AuthError(Exception):
    pass


def _extract_jwt_from_authorization(request: Request) -> str | None:
    return request.headers.get("x-auth-request-access-token")


async def _http_get_json(url: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
        r = await client.get(url)
        r.raise_for_status()
        data = r.json()
        if not isinstance(data, dict):
            raise AuthError("HTTP JSON response is not an object")
        return data


def _issuer_to_discovery_url(issuer: str) -> str:
    return issuer.rstrip("/") + "/.well-known/openid-configuration"


async def _get_discovery(issuer: str) -> dict[str, Any]:
    now = time.time()
    async with _cache_lock:
        cached = _discovery_cache.get(issuer)
        if cached and cached[0] > now:
            return cached[1]

    discovery = await _http_get_json(_issuer_to_discovery_url(issuer))

    async with _cache_lock:
        _discovery_cache[issuer] = (now + _DISCOVERY_TTL_SECONDS, discovery)

    return discovery


async def _get_jwks(jwks_url: str) -> dict[str, Any]:
    now = time.time()
    async with _cache_lock:
        cached = _jwks_cache.get(jwks_url)
        if cached and cached[0] > now:
            return cached[1]

    jwks = await _http_get_json(jwks_url)

    async with _cache_lock:
        _jwks_cache[jwks_url] = (now + _JWKS_TTL_SECONDS, jwks)

    return jwks


def _select_jwk(jwks: dict[str, Any], kid: str) -> dict[str, Any]:
    keys = jwks.get("keys", [])
    if not isinstance(keys, list):
        raise AuthError("JWKS keys is not a list")
    for key in keys:
        if isinstance(key, dict) and key.get("kid") == kid:
            return key
    raise AuthError("No matching JWK for kid")


def _best_effort_user_from_claims(claims: dict[str, Any]) -> str | None:
    for k in ("name", "preferred_username", "email", "user", "sub", "uid"):
        v = claims.get(k)
        if isinstance(v, str) and v:
            return v
    return None


def _unverified_issuer(token: str) -> str | None:
    claims = jwt.get_unverified_claims(token)
    iss = claims.get("iss")
    return iss if isinstance(iss, str) and iss else None


async def _jwks_url_from_token(token: str) -> str:
    iss = _unverified_issuer(token)
    if not iss:
        raise AuthError("JWT missing iss claim")

    if settings.oauth2_issuer and iss != settings.oauth2_issuer:
        raise AuthError("JWT issuer mismatch")

    discovery = await _get_discovery(iss)
    jwks_uri = discovery.get("jwks_uri")
    if not isinstance(jwks_uri, str) or not jwks_uri:
        raise AuthError("OIDC discovery missing jwks_uri")

    return jwks_uri


def _verify_jwt(token: str, jwks: dict[str, Any]) -> dict[str, Any]:
    headers = jwt.get_unverified_header(token)
    kid = headers.get("kid")
    if not kid:
        raise AuthError("JWT missing kid header")

    jwk = _select_jwk(jwks, kid)

    issuer = settings.oauth2_issuer
    audience = settings.oauth2_audience
    return jwt.decode(
        token,
        jwk,
        algorithms=[headers.get("alg", "RS256")],
        issuer=issuer,
        audience=audience,
        options={
            "verify_signature": True,
            "verify_aud": audience is not None,
            "verify_iss": issuer is not None,
        },
    )


async def get_user_identity(request: Request) -> UserIdentity:
    token = _extract_jwt_from_authorization(request)
    if not token:
        raise AuthError("No user identity found (missing headers/JWT)")

    try:
        jwks_url = await _jwks_url_from_token(token)
        jwks = await _get_jwks(jwks_url)
        claims = _verify_jwt(token, jwks)
        user_id = _best_effort_user_from_claims(claims) or "unknown"
        return UserIdentity(
            user_id=user_id, raw={"source": "jwt-verified", "claims": claims}
        )
    except Exception as e:
        raise AuthError(f"JWT verification failed: {e}") from e
