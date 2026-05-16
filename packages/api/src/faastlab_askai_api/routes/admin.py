"""Tenant admin — list users, generate share-link invites, revoke them.

Invites are signed JWTs (no DB row needed for Pro v0.1; revocation by
rotating JWT_SECRET is the escape hatch). The recipient hits
`/accept?token=...` in the browser, sets a password, and a new User row
is created bound to the inviter's tenant.

Owner-only routes; we reject non-owners with 403.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime
from uuid import UUID

import jwt
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import desc, select

from faastlab_askai_core.adapters import Principal
from faastlab_askai_core.config import get_settings
from faastlab_askai_core.db import Tenant, User, get_sessionmaker

from faastlab_askai_api.middleware.principal import get_principal
from faastlab_askai_api.security import (
    WeakPasswordError,
    hash_password,
)

log = logging.getLogger(__name__)

router = APIRouter(tags=["admin"], prefix="/admin")

# Invite JWT carries `invite: true` so accept-invite endpoint can
# distinguish it from a regular session token.
_INVITE_AUD = "askai-invite"
_INVITE_DEFAULT_TTL_SECONDS = 60 * 60 * 24 * 7  # 7 days


def _require_owner(principal: Principal = Depends(get_principal)) -> Principal:
    """Only tenant owners can manage invites + users."""
    if "*" in principal.scopes or "owner" in principal.scopes:
        return principal
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="owner role required",
    )


# ---- DTOs -------------------------------------------------------------------


class UserRow(BaseModel):
    id: str
    email: str
    full_name: str | None
    role: str
    is_active: bool
    last_login_at: datetime | None
    created_at: datetime


class InviteCreate(BaseModel):
    email: EmailStr | None = Field(
        default=None,
        description=(
            "Optional — recorded on the invite for the admin's bookkeeping "
            "but not required (share-link works with any recipient)."
        ),
    )
    role: str = Field(default="member", pattern="^(member|admin)$")
    ttl_hours: int = Field(default=168, ge=1, le=720)  # 1h..30d


class InviteResponse(BaseModel):
    token: str
    accept_url: str
    role: str
    expires_at: datetime
    note: str = (
        "Share this link with the invitee. They'll set their password and "
        "join your workspace. The link is single-use; copy it now — we "
        "won't show it again."
    )


# ---- Routes -----------------------------------------------------------------


@router.get("/users", response_model=list[UserRow])
async def list_users(
    principal: Principal = Depends(_require_owner),
) -> list[UserRow]:
    sm = get_sessionmaker()
    async with sm() as session:
        rows = await session.execute(
            select(User)
            .where(User.tenant_id == principal.tenant_id)
            .order_by(desc(User.created_at))
        )
        users = rows.scalars().all()
    return [
        UserRow(
            id=str(u.id),
            email=u.email,
            full_name=u.full_name,
            role=u.role,
            is_active=u.is_active,
            last_login_at=u.last_login_at,
            created_at=u.created_at,
        )
        for u in users
    ]


@router.post("/invites", response_model=InviteResponse, status_code=201)
async def create_invite(
    body: InviteCreate,
    principal: Principal = Depends(_require_owner),
) -> InviteResponse:
    settings = get_settings()
    ttl = body.ttl_hours * 3600
    now = int(time.time())
    payload = {
        "invite": True,
        "tenant": principal.tenant_slug,
        "tenant_id": str(principal.tenant_id),
        "role": body.role,
        "invited_email": body.email,
        "invited_by": principal.user_id,
        "iat": now,
        "exp": now + ttl,
        "aud": _INVITE_AUD,
        "iss": settings.jwt_issuer,
    }
    token = jwt.encode(
        payload, settings.jwt_secret, algorithm=settings.jwt_algorithm
    )

    # Accept-URL pattern: the SPA reads ?token=... from /accept and POSTs
    # to /v1/auth/accept-invite. We return the relative URL so any FE
    # host works (the CLI / SDK can prepend a base if needed).
    accept_url = f"/accept?token={token}"

    log.info(
        "invite: tenant=%s role=%s invited_email=%s ttl_hours=%d by=%s",
        principal.tenant_slug,
        body.role,
        body.email or "(no email)",
        body.ttl_hours,
        principal.user_id,
    )

    return InviteResponse(
        token=token,
        accept_url=accept_url,
        role=body.role,
        expires_at=datetime.fromtimestamp(payload["exp"]),
    )


# ---- Accept invite (no auth required; the token IS the auth) ---------------


class AcceptInviteRequest(BaseModel):
    token: str
    password: str = Field(min_length=8, max_length=256)
    full_name: str | None = Field(default=None, max_length=256)
    email: EmailStr  # the joiner sets their own email (invite token doesn't pin it)


_acceptance_router = APIRouter(tags=["auth"])


@_acceptance_router.post("/auth/accept-invite", status_code=201)
async def accept_invite(body: AcceptInviteRequest) -> dict[str, object]:
    """Claim an invite token. Creates a User in the inviter's tenant.

    No auth: the invite token itself is the credential. We verify it
    against the same JWT_SECRET used to sign it on create.
    """
    settings = get_settings()
    try:
        claims = jwt.decode(
            body.token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            audience=_INVITE_AUD,
            issuer=settings.jwt_issuer,
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(
            status_code=400, detail=f"invalid or expired invite: {exc}"
        ) from exc

    if not claims.get("invite"):
        raise HTTPException(status_code=400, detail="not an invite token")

    tenant_slug = claims.get("tenant")
    tenant_id_str = claims.get("tenant_id")
    role = claims.get("role", "member")
    if not tenant_slug or not tenant_id_str:
        raise HTTPException(status_code=400, detail="malformed invite token")

    try:
        tenant_uuid = UUID(tenant_id_str)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="malformed tenant id") from exc

    try:
        pwd_hash = hash_password(body.password)
    except WeakPasswordError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    sm = get_sessionmaker()
    async with sm() as session:
        # Confirm the tenant still exists and is active.
        tenant_row = await session.execute(
            select(Tenant).where(Tenant.id == tenant_uuid)
        )
        tenant = tenant_row.scalar_one_or_none()
        if tenant is None or not tenant.is_active:
            raise HTTPException(status_code=410, detail="workspace no longer available")

        # Email uniqueness — same constraint as signup.
        existing = await session.execute(
            select(User.id).where(User.email == body.email.lower())
        )
        if existing.scalar_one_or_none() is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="email already registered",
            )

        user = User(
            tenant_id=tenant.id,
            email=body.email.lower(),
            password_hash=pwd_hash,
            full_name=body.full_name,
            role=role,
            is_active=True,
        )
        session.add(user)
        await session.commit()

        log.info(
            "invite accepted: tenant=%s email=%s role=%s",
            tenant_slug, body.email, role,
        )

    return {
        "status": "ok",
        "tenant_slug": tenant_slug,
        "tenant_name": tenant.name,
        "role": role,
        "next": "/login",
    }


# Re-exported so main.py can mount it under /v1.
acceptance_router = _acceptance_router
