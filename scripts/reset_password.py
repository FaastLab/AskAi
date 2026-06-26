"""Admin password reset — set a user's password directly (stopgap until the
self-service reset-link flow ships).

Run inside the api container (it has the security module + DB):

    docker compose exec -T api python - user@example.com 'NewPassw0rd!' < scripts/reset_password.py

Args: <email> <new_password>. The new password must pass the same strength
rules as signup (>= 8 chars, etc.) or it's rejected. Reuses hash_password so the
stored hash is identical to what login expects.

Note: the password appears in your shell history / process list — clear it
(`history -d`) on a shared box, or rotate it after the user logs in.
"""

from __future__ import annotations

import asyncio
import sys

from sqlalchemy import select

from faastlab_askai_api.security import WeakPasswordError, hash_password
from faastlab_askai_core.db import Tenant, User, get_sessionmaker


async def main() -> int:
    if len(sys.argv) < 3:
        print("usage: reset_password.py <email> <new_password>", file=sys.stderr)
        return 2
    email = sys.argv[1].strip().lower()
    new_password = sys.argv[2]

    try:
        pwd_hash = hash_password(new_password)
    except WeakPasswordError as exc:
        print(f"Weak password: {exc}", file=sys.stderr)
        return 1

    sm = get_sessionmaker()
    async with sm() as session:
        row = (
            await session.execute(
                select(User, Tenant)
                .join(Tenant, Tenant.id == User.tenant_id)
                .where(User.email == email)
            )
        ).first()
        if row is None:
            print(f"No user with email '{email}'.", file=sys.stderr)
            return 1
        user, tenant = row
        user.password_hash = pwd_hash
        await session.commit()
        print(
            f"Password reset for {user.email} (tenant={tenant.slug}, role={user.role}).",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
