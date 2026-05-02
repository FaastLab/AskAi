"""Search CLI — runs a query against an indexed tenant and prints hits."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from uuid import UUID

from sqlalchemy import select

from faastlab_askai_core.db import Tenant, get_sessionmaker

from faastlab_askai_search.filters import SearchFilters
from faastlab_askai_search.service import SearchService


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
    parser = argparse.ArgumentParser(prog="askai-search")
    parser.add_argument("--tenant", required=True, help="Tenant slug or UUID")
    parser.add_argument("--query", required=True, help="Search query")
    parser.add_argument("--k", type=int, default=5, help="How many hits to return")
    parser.add_argument(
        "--include-superseded",
        action="store_true",
        help="Include documents marked as superseded",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON instead of pretty text",
    )
    args = parser.parse_args(argv)

    tenant_id = await _resolve_tenant(args.tenant)
    service = SearchService()
    outcome = await service.search(
        tenant_id=tenant_id,
        query=args.query,
        k=args.k,
        filters=SearchFilters(only_active=not args.include_superseded),
    )

    if args.json:
        print(json.dumps(
            {
                "query": outcome.query,
                "confidence": outcome.confidence,
                "latency_ms": outcome.latency_ms,
                "hits": [
                    {
                        "rank": h.rank,
                        "score": h.score,
                        "doc": h.document_title,
                        "page": h.page_number,
                        "section": h.section_path,
                        "snippet": h.content[:300],
                        "is_active": h.is_active,
                    }
                    for h in outcome.hits
                ],
            },
            indent=2,
        ))
    else:
        print(f"\nQuery     : {outcome.query}")
        print(f"Confidence: {outcome.confidence:.2f}")
        print(f"Latency   : {outcome.latency_ms} ms\n")
        if not outcome.hits:
            print("(no results)")
            return 1
        for h in outcome.hits:
            tag = "" if h.is_active else "  [SUPERSEDED]"
            print(
                f"#{h.rank}  score={h.score:.4f}{tag}\n"
                f"     {h.document_title} — page {h.page_number}\n"
                f"     {h.content[:240].strip()}…\n"
            )
    return 0


def main() -> int:
    return asyncio.run(main_async(sys.argv[1:]))


if __name__ == "__main__":
    raise SystemExit(main())
