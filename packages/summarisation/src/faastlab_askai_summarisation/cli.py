"""Summarisation CLI — useful for the demo flow."""

from __future__ import annotations

import argparse
import asyncio
import sys
from uuid import UUID

from sqlalchemy import select

from faastlab_askai_core.db import Document, Tenant, get_sessionmaker

from faastlab_askai_summarisation.service import SummarisationService


async def _resolve_tenant(slug_or_id: str) -> UUID:
    try:
        return UUID(slug_or_id)
    except ValueError:
        pass
    sm = get_sessionmaker()
    async with sm() as session:
        result = await session.execute(
            select(Tenant.id).where(Tenant.slug == slug_or_id)
        )
        row = result.scalar_one_or_none()
        if row is None:
            raise SystemExit(f"No tenant matches slug/uuid: {slug_or_id!r}")
        return row


async def main_async(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="askai-summarise")
    parser.add_argument("--tenant", required=True)
    parser.add_argument(
        "--document",
        help="Document UUID. Omit to summarise every doc in the tenant.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-summarise even if a summary already exists.",
    )
    args = parser.parse_args(argv)

    tenant_id = await _resolve_tenant(args.tenant)
    service = SummarisationService()

    if args.document:
        result = await service.summarise_document(
            tenant_id=tenant_id, document_id=UUID(args.document)
        )
        print(f"Document {result.document_id}: {result.slices_used} slices, "
              f"{len(result.keyphrases)} keyphrases\n")
        print(result.summary)
        return 0

    sm = get_sessionmaker()
    async with sm() as session:
        rows = await session.execute(
            select(Document.id, Document.title, Document.summary).where(
                Document.tenant_id == tenant_id
            )
        )
        docs = rows.all()

    total = 0
    for row in docs:
        if row.summary and not args.force:
            print(f"[SKIP] {row.title} (already summarised — use --force to redo)")
            continue
        result = await service.summarise_document(
            tenant_id=tenant_id, document_id=row.id
        )
        total += 1
        print(f"[OK]   {row.title} → {result.slices_used} slices")

    print(f"\nDone. Summarised={total}  Skipped={len(docs) - total}")
    return 0


def main() -> int:
    return asyncio.run(main_async(sys.argv[1:]))


if __name__ == "__main__":
    raise SystemExit(main())
