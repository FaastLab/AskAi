"""Sign-up, login, and current-user endpoints.

Each sign-up creates a brand-new Tenant + User-as-owner; we never share
tenants across sign-ups (multi-user invites are a separate route in v2).
Trial mode is the default: `trial_expires_at = now + N days`, configurable
via `TRIAL_DAYS` setting. Stripe webhooks will later clear that field
when a subscription becomes active.
"""

from __future__ import annotations

import logging
import re
import unicodedata
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select

from faastlab_askai_core.adapters import Principal
from faastlab_askai_core.config import get_settings
from faastlab_askai_core.db import AuditLog, Tenant, User, get_sessionmaker

from faastlab_askai_api.middleware.principal import get_principal, mint_jwt
from faastlab_askai_api.security import (
    WeakPasswordError,
    hash_password,
    verify_password,
)

log = logging.getLogger(__name__)

router = APIRouter(tags=["auth"], prefix="/auth")


# ---- DTOs -------------------------------------------------------------------


class SignupRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=256)
    full_name: str | None = Field(default=None, max_length=256)
    organisation: str = Field(
        min_length=2,
        max_length=256,
        description="Display name for the firm — becomes the tenant name.",
    )


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds
    user: "UserRead"


class UserRead(BaseModel):
    id: str
    email: str
    full_name: str | None
    role: str
    tenant_id: str
    tenant_slug: str
    tenant_name: str
    plan: str | None
    trial_expires_at: datetime | None
    trial_remaining_days: int | None


AuthResponse.model_rebuild()


# ---- Routes -----------------------------------------------------------------


@router.post("/signup", response_model=AuthResponse, status_code=201)
async def signup(body: SignupRequest) -> AuthResponse:
    """Create a brand-new tenant + owner user. Returns a JWT.

    Tenant slug is derived from the organisation name with a short
    uniqueness suffix; no collision retries needed because the suffix
    is six random hex chars.
    """
    settings = get_settings()
    sm = get_sessionmaker()
    async with sm() as session:
        # Email-uniqueness check first (cheaper than tenant creation).
        existing = await session.execute(
            select(User.id).where(User.email == body.email.lower())
        )
        if existing.scalar_one_or_none() is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="email already registered",
            )

        try:
            pwd_hash = hash_password(body.password)
        except WeakPasswordError as exc:
            raise HTTPException(
                status_code=400, detail=str(exc)
            ) from exc

        # Build a tenant slug — deterministic prefix + random suffix.
        slug = _slugify(body.organisation) + "-" + uuid.uuid4().hex[:6]
        trial_days = settings.trial_default_days
        trial_until = (
            datetime.now(timezone.utc) + timedelta(days=trial_days)
            if trial_days > 0
            else None
        )

        tenant = Tenant(
            slug=slug,
            name=body.organisation.strip(),
            is_active=True,
            trial_expires_at=trial_until,
            plan="trial",
        )
        session.add(tenant)
        await session.flush()  # populates tenant.id

        user = User(
            tenant_id=tenant.id,
            email=body.email.lower(),
            password_hash=pwd_hash,
            full_name=body.full_name,
            role="owner",
            is_active=True,
            last_login_at=datetime.now(timezone.utc),
        )
        session.add(user)
        await session.commit()

        log.info(
            "signup: tenant=%s user=%s plan=trial expires=%s",
            slug, user.email, trial_until,
        )
        await _audit_event(
            tenant_id=tenant.id,
            user_id=str(user.id),
            action="signup",
            summary=f"New workspace '{tenant.name}' (trial expires {trial_until})",
        )
        return _auth_response(user, tenant)


@router.post("/login", response_model=AuthResponse)
async def login(body: LoginRequest, request: Request) -> AuthResponse:
    sm = get_sessionmaker()
    async with sm() as session:
        result = await session.execute(
            select(User, Tenant)
            .join(Tenant, User.tenant_id == Tenant.id)
            .where(User.email == body.email.lower())
        )
        row = result.first()
        if row is None:
            # Run a dummy verify anyway so timing attacks can't probe for
            # registered emails. We discard the result.
            verify_password(body.password, "$2b$12$" + "x" * 53)
            _login_failed(request)
        user, tenant = row
        if not user.is_active:
            _login_failed(request, reason="inactive user")
        if not tenant.is_active:
            _login_failed(request, reason="inactive tenant")
        if not verify_password(body.password, user.password_hash):
            _login_failed(request)

        user.last_login_at = datetime.now(timezone.utc)
        await session.commit()
        log.info("login: tenant=%s user=%s", tenant.slug, user.email)
        await _audit_event(
            tenant_id=tenant.id,
            user_id=str(user.id),
            action="login",
            summary=(
                f"Login from {request.client.host if request.client else 'unknown'} "
                f"as {user.email}"
            ),
        )
        return _auth_response(user, tenant)


@router.get("/me", response_model=UserRead)
async def me(
    principal: Principal = Depends(get_principal),
) -> UserRead:
    sm = get_sessionmaker()
    async with sm() as session:
        result = await session.execute(
            select(User, Tenant)
            .join(Tenant, User.tenant_id == Tenant.id)
            .where(User.email == (principal.email or ""))
        )
        row = result.first()
        if row is None:
            # Dev-mode default-tenant principal or a JWT for a deleted
            # user — return a synthetic record so the UI can still render.
            return UserRead(
                id="anonymous",
                email=principal.email or "demo@local",
                full_name=None,
                role="member",
                tenant_id=str(principal.tenant_id),
                tenant_slug=principal.tenant_slug,
                tenant_name=principal.tenant_slug,
                plan="demo",
                trial_expires_at=None,
                trial_remaining_days=None,
            )
        user, tenant = row
        return _user_read(user, tenant)


# ---- helpers ----------------------------------------------------------------


def _auth_response(user: User, tenant: Tenant) -> AuthResponse:
    settings = get_settings()
    ttl = settings.jwt_token_ttl_seconds
    token = mint_jwt(
        user_id=str(user.id),
        tenant_slug=tenant.slug,
        scopes=[user.role, "*"] if user.role == "owner" else [user.role],
        ttl_seconds=ttl,
        email=user.email,
        settings=settings,
    )
    return AuthResponse(
        access_token=token,
        expires_in=ttl,
        user=_user_read(user, tenant),
    )


def _user_read(user: User, tenant: Tenant) -> UserRead:
    remaining: int | None = None
    if tenant.trial_expires_at is not None:
        delta = tenant.trial_expires_at - datetime.now(timezone.utc)
        remaining = max(0, delta.days)
    return UserRead(
        id=str(user.id),
        email=user.email,
        full_name=user.full_name,
        role=user.role,
        tenant_id=str(tenant.id),
        tenant_slug=tenant.slug,
        tenant_name=tenant.name,
        plan=tenant.plan,
        trial_expires_at=tenant.trial_expires_at,
        trial_remaining_days=remaining,
    )


def _login_failed(request: Request, *, reason: str = "bad credentials") -> None:
    """Same 401 for every reason — never leak whether the email exists."""
    log.warning(
        "login failed: %s from %s",
        reason,
        request.client.host if request.client else "?",
    )
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="invalid email or password",
    )


async def _audit_event(
    *,
    tenant_id,  # UUID
    user_id: str,
    action: str,
    summary: str,
) -> None:
    """Inline audit write for auth events (signup, login, accept-invite).

    We can't use the route-level audit helper here because that wants a
    Principal — and Principal isn't built yet at signup/login time.
    Best-effort: any DB failure is swallowed.
    """
    from sqlalchemy import insert

    try:
        async with get_sessionmaker()() as session:
            await session.execute(
                insert(AuditLog).values(
                    tenant_id=tenant_id,
                    user_id=user_id,
                    action=action,
                    resource="/v1/auth",
                    response_summary=summary,
                    sources={"items": []},
                    extra={},
                )
            )
            await session.commit()
    except Exception:  # noqa: BLE001
        log.exception("audit: failed to record auth event %s for %s", action, user_id)


def _slugify(name: str) -> str:
    """Lower-case, alphanumeric-and-hyphen tenant slug."""
    norm = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-zA-Z0-9]+", "-", norm).strip("-").lower()
    return s[:32] if s else "tenant"
