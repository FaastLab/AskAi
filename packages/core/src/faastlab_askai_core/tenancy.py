"""Tenancy helpers — public corpus resolution + visible-tenant lists.

The public corpus is a designated tenant (`settings.public_corpus_tenant_slug`)
whose documents are visible to ALL signed-in tenants. This is how we
implement the "regulator corpus" tier: imported once into one tenant,
read by everyone.

Caching: we cache the resolved tenant id at module level keyed on slug.
Cache is invalidated only when the process restarts — fine because the
tenant id is stable once created.
"""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy import select

from faastlab_askai_core.config import get_settings
from faastlab_askai_core.db import Tenant, get_sessionmaker

log = logging.getLogger(__name__)

# Process-scoped cache. Slug → UUID (or None = "no shared corpus configured").
_cache: dict[str, UUID | None] = {}


async def get_public_corpus_tenant_id() -> UUID | None:
    """Resolve the configured public corpus tenant id, or None if disabled."""
    settings = get_settings()
    slug = (settings.public_corpus_tenant_slug or "").strip()
    if not slug:
        return None
    if slug in _cache:
        return _cache[slug]
    sm = get_sessionmaker()
    async with sm() as session:
        result = await session.execute(
            select(Tenant.id).where(Tenant.slug == slug)
        )
        tenant_id = result.scalar_one_or_none()
    if tenant_id is None:
        log.warning(
            "public_corpus_tenant_slug=%r does not match any tenant — "
            "the shared regulator corpus will be empty for signed-in users",
            slug,
        )
    _cache[slug] = tenant_id
    return tenant_id


async def visible_tenant_ids(caller_tenant_id: UUID) -> list[UUID]:
    """Return the tenant IDs the caller can read across.

    Always includes the caller's own tenant. Adds the public corpus tenant
    if configured AND it isn't already the caller's tenant (deduped).
    """
    public_id = await get_public_corpus_tenant_id()
    if public_id is None or public_id == caller_tenant_id:
        return [caller_tenant_id]
    return [caller_tenant_id, public_id]
