from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any

import httpx
from fastapi import Request
from jose import jwt
from pydantic import BaseModel, Field

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


class UserInfo(BaseModel):
    user_id: str = Field(default="")
    username: str = Field(default="")
    full_name: str = Field(default="")
    first_name: str = Field(default="")
    last_name: str = Field(default="")
    email: str = Field(default="")
    groups: list[str] = Field(default_factory=list)
    is_admin: bool = Field(default=False)

    @staticmethod
    def from_identity(user: UserIdentity) -> "UserInfo":
        info = UserInfo()
        claims = user.raw.get("claims", {}) or {}

        info.user_id = user.user_id
        info.username = (
            claims.get("sub", "") or claims.get("preferred_username", "") or ""
        )
        info.full_name = claims.get("name", "") or ""
        info.first_name = claims.get("given_name", "") or ""
        info.last_name = claims.get("family_name", "") or ""
        info.email = claims.get("email", "") or ""

        groups = claims.get("groups", []) or []
        if isinstance(groups, str):
            groups = [g.strip() for g in groups.split(",") if g.strip()]
        info.groups = list(groups)

        info.is_admin = settings.admin_group in set(info.groups)
        return info


class AuthError(Exception):
    pass


def is_admin(user: UserIdentity) -> bool:
    claims = user.raw.get("claims", {}) or {}
    groups = claims.get("groups", []) or []
    if isinstance(groups, str):
        groups = [g.strip() for g in groups.split(",") if g.strip()]
    return settings.admin_group in set(groups)


def _extract_jwt_from_authorization(request: Request) -> str | None:
    return request.headers.get("x-auth-request-access-token")


def _issuer_to_discovery_url(issuer: str) -> str:
    return issuer.rstrip("/") + "/.well-known/openid-configuration"


async def _http_get_json(url: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
        r = await client.get(url)
        r.raise_for_status()
        data = r.json()
        if not isinstance(data, dict):
            raise AuthError("HTTP JSON response is not an object")
        return data


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
    for k in ("sid", "sub", "preferred_username", "name", "email", "user", "uid"):
        v = claims.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return None


def _unverified_issuer(token: str) -> str | None:
    claims = jwt.get_unverified_claims(token)
    iss = claims.get("iss")
    return iss if isinstance(iss, str) and iss else None


async def _jwks_url_from_token(token: str) -> str:
    if settings.oauth2_jwks_url:
        return settings.oauth2_jwks_url

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


def _trusted_identity_from_headers(request: Request) -> UserIdentity | None:
    if not settings.oauth2_trust_headers:
        return None

    user = request.headers.get("x-auth-request-user") or request.headers.get(
        "x-auth-request-email"
    )
    if not user:
        return None

    groups_raw = (
        request.headers.get("x-auth-request-groups")
        or request.headers.get("x-auth-request-user-groups")
        or ""
    )
    groups = [g.strip() for g in groups_raw.split(",") if g.strip()]

    claims: dict[str, Any] = {
        "sub": user,
        "email": request.headers.get("x-auth-request-email") or "",
        "name": request.headers.get("x-auth-request-preferred-username") or user,
        "groups": groups,
    }

    return UserIdentity(
        user_id=user, raw={"source": "trusted-headers", "claims": claims}
    )


async def get_user_identity(request: Request) -> UserIdentity:
    token = _extract_jwt_from_authorization(request)

    if token:
        try:
            jwks_url = await _jwks_url_from_token(token)
            jwks = await _get_jwks(jwks_url)
            claims = _verify_jwt(token, jwks)
            user_id = _best_effort_user_from_claims(claims) or "unknown"
            return UserIdentity(
                user_id=user_id, raw={"source": "jwt-verified", "claims": claims}
            )
        except Exception as e:
            hdr_user = _trusted_identity_from_headers(request)
            if hdr_user:
                return hdr_user
            raise AuthError(f"JWT verification failed: {e}") from e

    hdr_user = _trusted_identity_from_headers(request)
    if hdr_user:
        return hdr_user

    raise AuthError("No user identity found (missing headers/JWT)")
