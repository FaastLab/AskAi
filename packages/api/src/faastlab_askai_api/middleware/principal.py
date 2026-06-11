"""Auth dependency — JWT bearer token → Principal.

Default uses `JWT_SECRET` HMAC. Production deployments would swap in an
OIDC verifier; the auth Protocol in core lets us add that without
touching route code.

For OSS dev convenience, when `app_env == "dev"` and no `Authorization`
header is supplied, we attach a synthetic Principal bound to the
`default_tenant` setting so first-time users can curl the API without
minting a token.
"""

from __future__ import annotations

import time
from uuid import UUID

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select

from faastlab_askai_core.adapters import Principal
from faastlab_askai_core.config import Settings, get_settings
from faastlab_askai_core.db import Tenant, get_sessionmaker
from faastlab_askai_core.exceptions import (
    AuthenticationError,
    TenantNotFoundError,
)

bearer = HTTPBearer(auto_error=False)


def rate_limit_key(request: Request) -> str:
    """Bucket rate limits by tenant (preferred) or remote IP fallback."""
    principal = getattr(request.state, "principal", None)
    if principal is not None:
        return f"tenant:{principal.tenant_slug}"
    client = request.client
    return f"ip:{client.host if client else 'unknown'}"


async def _resolve_tenant_id(slug: str) -> UUID:
    sm = get_sessionmaker()
    async with sm() as session:
        result = await session.execute(
            select(Tenant.id).where(Tenant.slug == slug)
        )
        row = result.scalar_one_or_none()
    if row is None:
        raise TenantNotFoundError(slug)
    return row


async def _principal_from_jwt(token: str, settings: Settings) -> Principal:
    try:
        claims = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            audience=settings.jwt_audience,
            issuer=settings.jwt_issuer,
        )
    except jwt.PyJWTError as exc:
        raise AuthenticationError(str(exc)) from exc

    tenant_slug = claims.get("tenant") or claims.get("tenant_slug")
    user_id = claims.get("sub") or claims.get("user_id")
    scopes = frozenset((claims.get("scopes") or "").split()) if claims.get("scopes") else frozenset()
    if not tenant_slug or not user_id:
        raise AuthenticationError("token missing 'tenant' or 'sub' claim")

    tenant_id = await _resolve_tenant_id(tenant_slug)
    return Principal(
        user_id=str(user_id),
        tenant_id=tenant_id,
        tenant_slug=tenant_slug,
        scopes=scopes,
        email=claims.get("email"),
    )


async def get_principal(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
) -> Principal:
    settings = get_settings()

    if creds is None:
        # Never fall back to an anonymous principal. Unauthenticated callers
        # get a 401, regardless of APP_ENV. Local dev should mint a real JWT
        # (see `tests/conftest.py` / `make dev-token`) rather than rely on a
        # magic-string env flag — fail-open auth is a CISO red line and we
        # had a real incident from it.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token",
        )

    try:
        principal = await _principal_from_jwt(creds.credentials, settings)
    except AuthenticationError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)
        ) from exc
    except TenantNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)
        ) from exc

    request.state.principal = principal
    return principal


def require_scope(scope: str):
    """Route dependency factory enforcing a scope claim."""

    def _check(principal: Principal = Depends(get_principal)) -> Principal:
        if "*" in principal.scopes or scope in principal.scopes:
            return principal
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"missing scope: {scope}",
        )

    return _check


# ---- Short-lived signed URLs for document-file downloads -----------------
#
# `/v1/documents/{id}/file` is loaded by the browser as a top-level navigation
# (anchor href / iframe src), which cannot carry an Authorization header. To
# keep that endpoint authenticated without leaking the long-lived bearer JWT
# in a query string, the SPA first calls `POST /v1/documents/{id}/file/
# signed-url` with its bearer, gets back a short-lived (5 min) JWT scoped to
# that one document, and embeds it as `?token=`. The file route accepts
# either Authorization: Bearer (programmatic clients) OR the query token.
#
# The signed token uses a DIFFERENT audience ("askai-file") than the main
# bearer ("askai"), so a leaked file token can't be replayed against
# /v1/ask, /v1/search, etc — those reject any token whose `aud` claim
# isn't `settings.jwt_audience`.

FILE_TOKEN_AUDIENCE = "askai-file"
FILE_TOKEN_TTL_SECONDS = 300


def mint_file_token(
    *,
    user_id: str,
    tenant_slug: str,
    document_id: UUID,
    settings: Settings | None = None,
    ttl_seconds: int = FILE_TOKEN_TTL_SECONDS,
) -> str:
    """Mint a 5-minute JWT scoped to a single document download."""
    s = settings or get_settings()
    now = int(time.time())
    payload = {
        "sub": user_id,
        "tenant": tenant_slug,
        "doc": str(document_id),
        "iat": now,
        "exp": now + ttl_seconds,
        "aud": FILE_TOKEN_AUDIENCE,
        "iss": s.jwt_issuer,
    }
    return jwt.encode(payload, s.jwt_secret, algorithm=s.jwt_algorithm)


async def verify_file_token(
    token: str,
    document_id: UUID,
    settings: Settings | None = None,
) -> tuple[str, UUID]:
    """Decode a file-scoped JWT and assert it's for THIS document.

    Returns (user_id, tenant_id). Raises HTTPException on any mismatch.
    """
    s = settings or get_settings()
    try:
        claims = jwt.decode(
            token,
            s.jwt_secret,
            algorithms=[s.jwt_algorithm],
            audience=FILE_TOKEN_AUDIENCE,
            issuer=s.jwt_issuer,
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"invalid file token: {exc}",
        ) from exc

    if claims.get("doc") != str(document_id):
        # Critical — without this check, a token minted for doc A could
        # be replayed against doc B in the same tenant.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="file token does not match this document",
        )

    tenant_slug = claims.get("tenant")
    user_id = claims.get("sub")
    if not tenant_slug or not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="file token missing 'tenant' or 'sub'",
        )

    try:
        tenant_id = await _resolve_tenant_id(str(tenant_slug))
    except TenantNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)
        ) from exc

    return str(user_id), tenant_id


def mint_jwt(
    *,
    user_id: str,
    tenant_slug: str,
    scopes: list[str],
    ttl_seconds: int = 3600,
    email: str | None = None,
    settings: Settings | None = None,
) -> str:
    """Helper for tests / dev — mint a JWT compatible with `_principal_from_jwt`."""
    s = settings or get_settings()
    now = int(time.time())
    payload = {
        "sub": user_id,
        "tenant": tenant_slug,
        "scopes": " ".join(scopes),
        "iat": now,
        "exp": now + ttl_seconds,
        "aud": s.jwt_audience,
        "iss": s.jwt_issuer,
        "email": email,
    }
    return jwt.encode(payload, s.jwt_secret, algorithm=s.jwt_algorithm)
