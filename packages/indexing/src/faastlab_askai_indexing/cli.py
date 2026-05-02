"""CLI for running the ingestion pipeline directly (no Celery).

Usage:
    uv run python -m faastlab_askai_indexing.cli \\
        --tenant demo-public --path ./corpus/uk_finreg/_downloads

Designed for the demo flow and for manual smoke tests on the VM.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from uuid import UUID

from sqlalchemy import select

from faastlab_askai_core.db import Tenant, get_sessionmaker

from faastlab_askai_indexing.connectors.filesystem import FilesystemConnector
from faastlab_askai_indexing.pipeline import IngestionPipeline


async def _resolve_tenant(slug_or_id: str) -> UUID:
    """Accept a tenant slug ('demo-public') or a UUID and return the UUID."""
    try:
        return UUID(slug_or_id)
    except ValueError:
        pass

    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        result = await session.execute(
            select(Tenant.id).where(Tenant.slug == slug_or_id)
        )
        row = result.scalar_one_or_none()
        if row is None:
            raise SystemExit(f"No tenant matches slug/uuid: {slug_or_id!r}")
        return row


async def main_async(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="askai-ingest")
    parser.add_argument(
        "--tenant", required=True, help="Tenant slug or UUID (e.g. demo-public)"
    )
    parser.add_argument(
        "--path", required=True, help="Filesystem path to ingest (file or dir)"
    )
    parser.add_argument(
        "--no-recurse", action="store_true", help="Do not recurse into subdirectories"
    )
    args = parser.parse_args(argv)

    tenant_id = await _resolve_tenant(args.tenant)
    pipeline = IngestionPipeline(tenant_id)
    connector = FilesystemConnector(args.path, recursive=not args.no_recurse)

    total = 0
    skipped = 0
    failed = 0
    async for result in pipeline.ingest(connector):
        if result.skipped and result.note.startswith("error:"):
            failed += 1
            print(f"[FAIL] {result.source_uri}: {result.note}", file=sys.stderr)
        elif result.skipped:
            skipped += 1
            print(f"[SKIP] {result.source_uri} ({result.note})")
        else:
            total += 1
            print(
                f"[OK]   {result.source_uri} → "
                f"document {result.document_id} ({result.chunks_written} chunks)"
            )

    print(f"\nDone. Ingested={total}  Skipped={skipped}  Failed={failed}")
    return 0 if failed == 0 else 1


def main() -> int:
    return asyncio.run(main_async(sys.argv[1:]))


if __name__ == "__main__":
    raise SystemExit(main())
