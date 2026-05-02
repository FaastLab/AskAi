"""ask-AI CLI — ask a question against an indexed tenant."""

from __future__ import annotations

import argparse
import asyncio
import sys
from uuid import UUID

from sqlalchemy import select

from faastlab_askai_core.db import Tenant, get_sessionmaker
from faastlab_askai_search.filters import SearchFilters

from faastlab_askai_askai.service import AskAiService


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
    parser = argparse.ArgumentParser(prog="askai-ask")
    parser.add_argument("--tenant", required=True, help="Tenant slug or UUID")
    parser.add_argument("--user", default="cli", help="User id (for audit)")
    parser.add_argument("--query", required=True, help="The question to ask")
    parser.add_argument("--session", default=None, help="Existing session UUID (optional)")
    parser.add_argument(
        "--include-superseded",
        action="store_true",
        help="Allow superseded documents in retrieval",
    )
    parser.add_argument(
        "--no-stream", action="store_true", help="Wait for the full answer (no streaming)"
    )
    args = parser.parse_args(argv)

    tenant_id = await _resolve_tenant(args.tenant)
    session_id = UUID(args.session) if args.session else None
    filters = SearchFilters(only_active=not args.include_superseded)
    service = AskAiService()

    if args.no_stream:
        outcome = await service.ask(
            tenant_id=tenant_id,
            user_id=args.user,
            question=args.query,
            session_id=session_id,
            filters=filters,
        )
        print(f"\n{outcome.answer}\n")
        _print_citations(outcome.citations)
        print(
            f"\n— session={outcome.session_id} "
            f"confidence={outcome.confidence:.2f} "
            f"retrieval_ms={outcome.retrieval_latency_ms} "
            f"total_ms={outcome.total_latency_ms}"
        )
        return 0

    print()
    final_session: str | None = None
    citations: list[dict[str, object]] = []
    async for event in service.stream_ask(
        tenant_id=tenant_id,
        user_id=args.user,
        question=args.query,
        session_id=session_id,
        filters=filters,
    ):
        kind = event.get("event")
        if kind == "token":
            sys.stdout.write(str(event.get("text", "")))
            sys.stdout.flush()
        elif kind == "done":
            final_session = str(event.get("session_id"))
            citations = list(event.get("citations") or [])  # type: ignore[arg-type]
        elif kind == "retrieve":
            chunks = event.get("chunks")
            confidence = event.get("confidence")
            sys.stdout.write(
                f"[retrieved {chunks} chunks · confidence={confidence}]\n\n"
            )
            sys.stdout.flush()

    print("\n")
    _print_citations_dicts(citations)
    if final_session:
        print(f"\n— session={final_session}")
    return 0


def _print_citations(cs: list) -> None:
    if not cs:
        print("(no citations — answer used no context, or no [N] tags emitted)")
        return
    print("Citations:")
    for c in cs:
        loc = c.document_title
        if c.page_number is not None:
            loc += f", page {c.page_number}"
        print(f"  - {loc} — {c.snippet}")


def _print_citations_dicts(cs: list[dict[str, object]]) -> None:
    if not cs:
        print("(no citations — answer used no context, or no [N] tags emitted)")
        return
    print("Citations:")
    for c in cs:
        loc = str(c.get("document_title"))
        page = c.get("page_number")
        if page is not None:
            loc += f", page {page}"
        print(f"  - {loc} — {c.get('snippet')}")


def main() -> int:
    return asyncio.run(main_async(sys.argv[1:]))


if __name__ == "__main__":
    raise SystemExit(main())
