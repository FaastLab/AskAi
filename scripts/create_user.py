"""Admin create-user — add a user to an EXISTING tenant with a password.

Run inside the api container (has the security module + DB):

    docker compose exec -T api python - alice@firm.com 'Passw0rd!' networkrail-demo admin < scripts/create_user.py

Args: <email> <password> <tenant_slug> [role]
  role defaults to "member"; valid: owner | admin | member.

Reuses hash_password (same bcrypt the login checks), enforces the signup
strength rules, and rejects a duplicate email. To create a brand-new tenant +
owner instead, use the normal /v1/auth/signup flow.

Note: the password appears in shell history / process list — clear it on a
shared box.
"""

from __future__ import annotations

import asyncio
import sys

from sqlalchemy import select

from faastlab_askai_api.security import WeakPasswordError, hash_password
from faastlab_askai_core.db import Tenant, User, get_sessionmaker

_VALID_ROLES = {"owner", "admin", "member"}


async def main() -> int:
    if len(sys.argv) < 4:
        print(
            "usage: create_user.py <email> <password> <tenant_slug> [role]",
            file=sys.stderr,
        )
        return 2
    email = sys.argv[1].strip().lower()
    password = sys.argv[2]
    tenant_slug = sys.argv[3].strip()
    role = (sys.argv[4].strip().lower() if len(sys.argv) > 4 else "member")

    if role not in _VALID_ROLES:
        print(f"Invalid role '{role}'. Use one of: {sorted(_VALID_ROLES)}", file=sys.stderr)
        return 1
    try:
        pwd_hash = hash_password(password)
    except WeakPasswordError as exc:
        print(f"Weak password: {exc}", file=sys.stderr)
        return 1

    sm = get_sessionmaker()
    async with sm() as session:
        tenant_id = (
            await session.execute(select(Tenant.id).where(Tenant.slug == tenant_slug))
        ).scalar_one_or_none()
        if tenant_id is None:
            print(f"No tenant with slug '{tenant_slug}'.", file=sys.stderr)
            return 1
        # Emails are unique across the system (signup enforces the same).
        exists = (
            await session.execute(select(User.id).where(User.email == email))
        ).scalar_one_or_none()
        if exists is not None:
            print(f"A user with email '{email}' already exists.", file=sys.stderr)
            return 1
        session.add(
            User(
                tenant_id=tenant_id,
                email=email,
                password_hash=pwd_hash,
                role=role,
            )
        )
        await session.commit()
    print(
        f"Created user {email} (tenant={tenant_slug}, role={role}).",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
