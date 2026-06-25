"""Backfill: fix documents whose title is a bare FCA sourcebook CODE.

Older FCA Handbook PDFs were ingested before the title-expansion fix, so their
stored title is just the module code (REC, CREDS, UKLR, …) instead of a readable
name. Re-running the indexer does NOT fix them — the pipeline skips unchanged
docs (same content_hash) before the title logic runs. This script re-titles them
IN PLACE: no re-crawl, no re-embed, no delete.

Run inside the api/worker container (it has the DB + the pipeline module):

    docker compose exec -T api python - < scripts/backfill_fca_titles.py            # all tenants
    docker compose exec -T api python - demo-public < scripts/backfill_fca_titles.py # one tenant

Reuses the SAME mapping the pipeline uses (`_expand_sourcebook_title`), so the
results match what a fresh ingest would now produce.
"""

from __future__ import annotations

import asyncio
import sys

from sqlalchemy import select

from faastlab_askai_core.db import Document, Tenant, get_sessionmaker

# Reuse the live mapping + expander so backfill == fresh-ingest behaviour.
from faastlab_askai_indexing.pipeline import (
    _FCA_SOURCEBOOK_TITLES,
    _expand_sourcebook_title,
)

# Bare codes we treat as "needs fixing" (case-insensitive match on the title).
_CODES = {code.upper() for code in _FCA_SOURCEBOOK_TITLES}


async def main() -> int:
    slug = sys.argv[1] if len(sys.argv) > 1 else None
    sm = get_sessionmaker()
    fixed = 0
    async with sm() as session:
        stmt = select(Document)
        if slug:
            tenant_id = (
                await session.execute(select(Tenant.id).where(Tenant.slug == slug))
            ).scalar_one_or_none()
            if tenant_id is None:
                print(f"No tenant with slug '{slug}'.", file=sys.stderr)
                return 1
            stmt = stmt.where(Document.tenant_id == tenant_id)

        docs = (await session.execute(stmt)).scalars().all()
        for doc in docs:
            current = (doc.title or "").strip()
            # Only touch docs whose title is exactly a bare sourcebook code —
            # never clobber a title that's already been set to something real.
            if current.upper() not in _CODES:
                continue
            new_title = _expand_sourcebook_title(current)
            if new_title and new_title != doc.title:
                print(f"  {current!r} -> {new_title!r}", file=sys.stderr)
                doc.title = new_title
                fixed += 1
        await session.commit()

    print(f"Re-titled {fixed} document(s).", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
