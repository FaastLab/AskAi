"""Mint a long-lived JWT for a tenant's owner — for headless clients (the voice
demo) that hold a static token with no browser to refresh it.

Run it INSIDE the api container, where JWT_SECRET + the DB are configured:

    docker compose exec -T api python - networkrail-demo < scripts/mint_demo_token.py

(Default tenant slug is "networkrail-demo"; pass another as the first argument.)
The printed token goes straight into the voice app's ASKAI_TOKEN. Default TTL is
10 years — long enough to "set once". Treat it like a password: anyone holding
it can query that tenant's corpus until JWT_SECRET is rotated.
"""

from __future__ import annotations

import asyncio
import sys

from sqlalchemy import select

from faastlab_askai_api.middleware.principal import mint_jwt
from faastlab_askai_core.db import Tenant, User, get_sessionmaker

TEN_YEARS_SECONDS = 10 * 365 * 24 * 60 * 60


async def main() -> int:
    slug = sys.argv[1] if len(sys.argv) > 1 else "networkrail-demo"
    sm = get_sessionmaker()
    async with sm() as session:
        # Prefer the owner; fall back to any user in the tenant.
        row = (
            await session.execute(
                select(User, Tenant)
                .join(Tenant, Tenant.id == User.tenant_id)
                .where(Tenant.slug == slug)
                .order_by((User.role == "owner").desc())
            )
        ).first()
    if row is None:
        print(f"No user found for tenant slug '{slug}'.", file=sys.stderr)
        return 1
    user, tenant = row
    token = mint_jwt(
        user_id=str(user.id),
        tenant_slug=tenant.slug,
        # Owners get the wildcard scope so the token can hit any tenant-scoped route.
        scopes=[user.role, "*"] if user.role == "owner" else [user.role],
        ttl_seconds=TEN_YEARS_SECONDS,
        email=user.email,
    )
    # Print ONLY the token on stdout so it's easy to capture into an env var.
    print(token)
    print(
        f"\n# tenant={tenant.slug} user={user.email} role={user.role} "
        f"ttl=10y — set this as ASKAI_TOKEN in the voice app.",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
