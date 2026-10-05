from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any

import httpx
from celine.sdk.auth import is_platform_admin as _claims_hold_platform_admin
from celine.sdk.auth import organization_groups, realm_roles
from fastapi import HTTPException, Request
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
    # The caller's realm roles (`realm_access.roles`). Platform level only: an
    # organization's groups are never listed here.
    roles: list[str] = Field(default_factory=list)
    # The caller's REC, or none: no REC organization, or more than one.
    community_id: str | None = Field(default=None)
    # May use the administrator endpoints: a platform administrator, or a manager of
    # the caller's own REC.
    is_admin: bool = Field(default=False)
    is_platform_admin: bool = Field(default=False)

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

        info.roles = realm_roles(claims)
        try:
            info.community_id = community_id_of(user)
        except CommunityConflict:
            info.community_id = None
        info.is_platform_admin = is_platform_admin(user)
        info.is_admin = info.is_platform_admin or (
            info.community_id is not None and can_manage(user, info.community_id)
        )
        return info


class AuthError(Exception):
    pass


class CommunityConflict(HTTPException):
    """The token names more than one REC, which a member never has.

    Refused rather than resolved: picking one would answer from one community's
    documents to a member of another.
    """

    def __init__(self, communities: list[str]) -> None:
        super().__init__(
            status_code=403,
            detail="Member of more than one renewable energy community; refusing to "
            "choose one",
        )
        self.communities = communities


def _first(value: Any) -> str | None:
    if isinstance(value, list):
        value = value[0] if value else None
    return value if isinstance(value, str) and value else None


def _claims(user: UserIdentity) -> dict[str, Any]:
    return user.raw.get("claims", {}) or {}


def rec_memberships(claims: dict[str, Any]) -> dict[str, list[str]]:
    """The REC organizations in the token, alias to the groups held inside each.

    The alias is the community id. Each list is that one organization's groups
    (`celine.sdk.auth.organization_groups`) and is valid only for it. KC 26 emits
    `type` flattened on the entry; the nested `attributes.type` is read as a fallback,
    as `celine-sdk` does.
    """
    orgs = claims.get("organization")
    if not isinstance(orgs, dict):
        return {}
    out: dict[str, list[str]] = {}
    for alias, data in orgs.items():
        if not isinstance(alias, str) or not alias or not isinstance(data, dict):
            continue
        attributes = data.get("attributes")
        org_type = _first(data.get("type")) or (
            _first(attributes.get("type")) if isinstance(attributes, dict) else None
        )
        if org_type == settings.rec_organization_type:
            out[alias] = organization_groups(claims, alias)
    return out


def community_id_of(user: UserIdentity) -> str | None:
    """The caller's REC, None when they have none; `CommunityConflict` for several."""
    memberships = rec_memberships(_claims(user))
    if len(memberships) > 1:
        log.warning(
            "multiple_communities_refused",
            extra={"user": user.user_id, "communities": sorted(memberships)},
        )
        raise CommunityConflict(sorted(memberships))
    return next(iter(memberships), None)


def is_platform_admin(user: UserIdentity) -> bool:
    """A platform administrator: may manage every community's knowledge.

    Exactly the holders of the `platform-admin` realm role (`realm_access.roles`, via
    `celine.sdk.auth.is_platform_admin`). An `admins` group inside an organization is
    not one, and neither is a realm group: the top-level `groups` claim grants nothing.
    """
    return _claims_hold_platform_admin(_claims(user))


def can_manage(user: UserIdentity, community_id: str) -> bool:
    """May share documents with, and remove them from, this community.

    A platform administrator, or a holder of one of `REC_MANAGER_GROUPS` inside that
    REC's own organization — never a group held in another one.
    """
    if is_platform_admin(user):
        return True
    groups = rec_memberships(_claims(user)).get(community_id, [])
    return any(g in groups for g in settings.rec_manager_groups)


def _extract_jwt_from_authorization(request: Request) -> str | None:
    return request.headers.get("x-auth-request-access-token")


def extract_access_token(request: Request) -> str | None:
    token = _extract_jwt_from_authorization(request)
    if token:
        return token

    authorization = request.headers.get("authorization")
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()

    cookie_name = settings.oauth2_jwt_cookie_name
    if cookie_name:
        cookie_token = request.cookies.get(cookie_name)
        if cookie_token:
            return cookie_token

    return None


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


def _user_id_from_claims(claims: dict[str, Any]) -> str | None:
    """The caller's stable id: the verified token's `sub`, and nothing else.

    Every stored row (conversations, messages, attachments, indexed documents) is keyed
    by it, and erasure or export of a person's data is asked for by `sub`. `sid` is the
    login session and changes on every login; a name or an email is neither unique nor
    stable. A token without `sub` names nobody, so it has no identity.
    """
    v = claims.get("sub")
    if isinstance(v, str) and v.strip():
        return v.strip()
    return None


def _unverified_issuer(token: str) -> str | None:
    claims = jwt.get_unverified_claims(token)
    iss = claims.get("iss")
    return iss if isinstance(iss, str) and iss else None


async def _jwks_url_from_token(token: str) -> str:
    # The key set used to verify a token must come from a trust anchor the operator
    # configured, never from the token itself. Deriving the JWKS location from the
    # token's own (unverified) `iss` lets a caller point verification at a key set they
    # control and mint any identity, administrator included — so a configured
    # `OAUTH2_JWKS_URL` or `OAUTH2_ISSUER` is required, and without one we refuse rather
    # than trust the token's self-declared issuer.
    if settings.oauth2_jwks_url:
        if settings.oauth2_issuer:
            iss = _unverified_issuer(token)
            if iss != settings.oauth2_issuer:
                raise AuthError("JWT issuer mismatch")
        return settings.oauth2_jwks_url

    if not settings.oauth2_issuer:
        raise AuthError(
            "token verification is not configured: set OAUTH2_JWKS_URL or "
            "OAUTH2_ISSUER (the token's self-declared issuer is not trusted)"
        )

    iss = _unverified_issuer(token)
    if not iss:
        raise AuthError("JWT missing iss claim")

    if iss != settings.oauth2_issuer:
        raise AuthError("JWT issuer mismatch")

    # Discover from the configured issuer, not the one the token names.
    discovery = await _get_discovery(settings.oauth2_issuer)
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
    # Algorithms are pinned by configuration, never taken from the token header: a
    # caller must not be able to choose the algorithm their token is verified against.
    #
    # A configured audience must also be present: python-jose compares `aud` only when
    # the token carries one, so a token with no `aud` at all (a service account's
    # client-credentials token, say) passed the audience check. A token without `exp`
    # would likewise never expire.
    return jwt.decode(
        token,
        jwk,
        algorithms=settings.oauth2_algorithms,
        issuer=issuer,
        audience=audience,
        options={
            "verify_signature": True,
            "verify_aud": audience is not None,
            "verify_iss": issuer is not None,
            "require_aud": audience is not None,
            "require_iss": issuer is not None,
            "require_exp": True,
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

    # An identity and nothing more. `x-auth-request-groups` is deliberately not read:
    # it is a flat list (oauth2-proxy's keycloak-oidc provider mixes `role:<name>`
    # entries into it), and platform roles are taken only from a verified token's
    # `realm_access.roles`. A header identity is never a platform administrator.
    claims: dict[str, Any] = {
        "sub": user,
        "email": request.headers.get("x-auth-request-email") or "",
        "name": request.headers.get("x-auth-request-preferred-username") or user,
    }

    return UserIdentity(
        user_id=user, raw={"source": "trusted-headers", "claims": claims}
    )


async def get_user_identity(request: Request) -> UserIdentity:
    token = extract_access_token(request)

    if token:
        # A token that is present and does not verify is a request to refuse, not one to
        # downgrade. Falling back to the trusted headers here made an expired or forged
        # token indistinguishable from no token at all — and with OAUTH2_TRUST_HEADERS
        # on, that is whatever identity the caller cared to assert.
        try:
            jwks_url = await _jwks_url_from_token(token)
            jwks = await _get_jwks(jwks_url)
            claims = _verify_jwt(token, jwks)
        except Exception as e:
            log.warning("jwt_verification_failed: %s", e)
            raise HTTPException(
                status_code=401, detail=f"JWT verification failed: {e}"
            ) from e

        user_id = _user_id_from_claims(claims)
        if not user_id:
            log.warning("jwt_without_subject")
            raise HTTPException(status_code=401, detail="JWT has no sub claim")
        return UserIdentity(
            user_id=user_id, raw={"source": "jwt-verified", "claims": claims}
        )

    hdr_user = _trusted_identity_from_headers(request)
    if hdr_user:
        return hdr_user

    raise HTTPException(status_code=401, detail="No user identity found (missing headers/JWT)")
