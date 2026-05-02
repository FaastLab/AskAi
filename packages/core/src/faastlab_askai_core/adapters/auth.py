"""Auth adapter — JWT, OIDC, Entra, Auth0."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable
from uuid import UUID


@dataclass(frozen=True, slots=True)
class Principal:
    """Authenticated caller — user identity plus tenant binding.

    `tenant_id` is enforced on every downstream query. No code path may
    operate without an authenticated `Principal` except the public
    health-check endpoint.
    """

    user_id: str
    tenant_id: UUID
    tenant_slug: str
    scopes: frozenset[str]
    email: str | None = None


@runtime_checkable
class AuthAdapter(Protocol):
    """Validates incoming credentials and returns a `Principal`."""

    async def authenticate(self, token: str) -> Principal:
        """Validate `token` (JWT, OIDC access token, etc.) and return the
        caller. Raises `AuthenticationError` if invalid."""
        ...
