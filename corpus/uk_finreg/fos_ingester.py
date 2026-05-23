"""FOS (Financial Ombudsman Service) final-decisions ingester.

FOS publishes every formal "final decision" issued by an ombudsman at
https://www.financial-ombudsman.org.uk/decisions-database/search. The
decisions are public, anonymised (no personal data), and reused widely
across the industry as de-facto precedent.

For the AskAi debt-collections vertical, having these searchable next to
the FCA Handbook is a step change — *"show me decisions like this
complaint"* is the #1 ask from compliance teams.

Pipeline:

1. Walk the public search HTML, paginating until no more results (or
   --max-pages, or --since cutoff is hit).
2. For each decision row, extract the metadata visible in the listing
   (DRN reference, business, product, outcome, date) and the link to
   the decision PDF.
3. Download the PDF via the shared `_download` helper (soft-404
   detection, on-disk cache) and push through `IngestionPipeline` —
   chunks, embeddings, the works.
4. Persist FOS metadata in the document's `metadata` JSONB so the UI
   can filter ("upheld only", "product=Credit cards", "year>=2024").

Design choices:

- **Respect robots.txt** — checked once at startup; aborts if disallowed.
- **Rate-limited** — default 1 req/sec to be a polite citizen on FOS's
  public infra. Override with --rate.
- **Incremental** — `--since YYYY-MM-DD` only ingests decisions newer
  than that date. The cron job will use the most recent fos_date in
  the DB as the cutoff.
- **Idempotent** — the underlying pipeline dedupes on content_hash,
  so re-running just resumes.
- **Defensive HTML parsing** — FOS could change their template
  anytime; we try multiple selector strategies and log clearly what
  worked and what didn't.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import urllib.robotparser
from datetime import UTC, date, datetime
from pathlib import Path
from uuid import UUID

import httpx
from sqlalchemy import select

from faastlab_askai_core.db import Tenant, get_sessionmaker
from faastlab_askai_indexing.connectors.base import SourceDocument
from faastlab_askai_indexing.parsers.router import detect_content_type
from faastlab_askai_indexing.pipeline import IngestionPipeline

from corpus.uk_finreg.fos_parser import (
    FOS_BASE,
    FosDecision,
    _parse_search_page,
)
from corpus.uk_finreg.handbook_ingester import (  # reuse shared helpers
    _download,
    _safe_filename,
)

log = logging.getLogger(__name__)

CORPUS_DIR = Path(__file__).resolve().parent
DOWNLOADS_DIR = CORPUS_DIR / "_downloads" / "fos"
DEFAULT_TENANT_SLUG = "demo-public"
USER_AGENT = "FaastLab-AskAi-FosIngester/0.1 (+https://faastlab.ai)"

SEARCH_URL = f"{FOS_BASE}/decisions-database/search"
ROBOTS_URL = f"{FOS_BASE}/robots.txt"


# ---------------------------------------------------------------------------
# Tenant + robots
# ---------------------------------------------------------------------------


async def _resolve_tenant(slug: str) -> UUID:
    sm = get_sessionmaker()
    async with sm() as session:
        result = await session.execute(select(Tenant.id).where(Tenant.slug == slug))
        row = result.scalar_one_or_none()
    if row is None:
        raise SystemExit(f"Tenant {slug!r} not found — run `make migrate` first?")
    return row


async def _check_robots(client: httpx.AsyncClient) -> bool:
    """Fetch robots.txt and confirm we may crawl /decisions-database/ and
    /decision/. Returns False (refuse to crawl) on disallow."""
    try:
        resp = await client.get(ROBOTS_URL)
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        log.warning("robots.txt fetch failed (%s) — proceeding cautiously", exc)
        return True

    rp = urllib.robotparser.RobotFileParser()
    rp.parse(resp.text.splitlines())
    for path in ("/decisions-database/", "/decision/"):
        if not rp.can_fetch(USER_AGENT, FOS_BASE + path):
            log.error("robots.txt disallows %s for %s — aborting", path, USER_AGENT)
            return False
    log.info("robots.txt: OK to crawl /decisions-database/ and /decision/")
    return True


# ---------------------------------------------------------------------------
# Crawl
# ---------------------------------------------------------------------------


async def _crawl_search(
    client: httpx.AsyncClient,
    *,
    max_pages: int,
    since: date | None,
    rate_sleep: float,
) -> list[FosDecision]:
    """Walk the FOS search results page by page until we run out, hit
    --max-pages, or hit a decision older than --since."""
    all_decisions: list[FosDecision] = []
    for page in range(1, max_pages + 1):
        url = f"{SEARCH_URL}?Sort=AcceptedDateDesc&Page={page}"
        log.info("FOS: fetching page %d", page)
        try:
            resp = await client.get(url, follow_redirects=True)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            log.warning("FOS page %d fetch failed: %s — stopping", page, exc)
            break

        page_decisions = _parse_search_page(resp.text)
        if not page_decisions:
            log.info("FOS: page %d returned no decisions — assuming end of results", page)
            break

        # Cutoff check
        keep = []
        hit_cutoff = False
        for d in page_decisions:
            if since and d.date_published and d.date_published < since:
                hit_cutoff = True
                continue
            keep.append(d)
        all_decisions.extend(keep)
        log.info(
            "FOS: page %d → %d decisions (kept %d, total %d)",
            page, len(page_decisions), len(keep), len(all_decisions),
        )
        if hit_cutoff:
            log.info("FOS: hit --since cutoff %s on page %d — done", since, page)
            break

        await asyncio.sleep(rate_sleep)

    return all_decisions


# ---------------------------------------------------------------------------
# Ingest
# ---------------------------------------------------------------------------


async def _ingest_decision(
    decision: FosDecision,
    *,
    pipeline: IngestionPipeline,
    http: httpx.AsyncClient,
    force: bool,
) -> tuple[str, str]:
    filename = _safe_filename(decision.pdf_url)
    dest = DOWNLOADS_DIR / filename

    fetched = await _download(http, decision.pdf_url, dest=dest, force=force)
    if fetched is None:
        return "failed", f"download failed: {decision.pdf_url}"

    data = fetched.read_bytes()
    if not data:
        return "failed", "empty download"

    metadata = {
        "regulator": "fos",
        "doc_type": "fos-decision",
        "source": "fos_ingester",
        "ogl_attribution": (
            "Reproduces a Financial Ombudsman Service final decision, "
            "published by the FOS for public reference. Personal data "
            "redacted by the FOS prior to publication."
        ),
        **{k: v for k, v in decision.metadata_dict().items() if v is not None},
    }

    title = decision.title or decision.drn
    if decision.business:
        title = f"{decision.drn}: {decision.business}"
    if decision.outcome:
        title = f"{title} ({decision.outcome})"

    source = SourceDocument(
        source_uri=decision.decision_url,
        data=data,
        filename=filename,
        content_type=detect_content_type(filename, default="application/pdf"),
        title=title,
        metadata=metadata,
    )

    try:
        result = await pipeline.ingest_one(source)
    except Exception as exc:  # noqa: BLE001
        log.exception("FOS ingest failed: %s", decision.drn)
        return "failed", f"ingest failed: {exc}"

    if result.skipped and result.note.startswith("error:"):
        return "failed", result.note
    if result.skipped:
        return "skipped", result.note or "already current"
    return "ok", f"{result.chunks_written} chunks"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def main_async(args: argparse.Namespace) -> int:
    logging.basicConfig(
        level=logging.WARNING if args.quiet else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        force=True,
    )

    since: date | None = None
    if args.since:
        try:
            since = datetime.strptime(args.since, "%Y-%m-%d").date()
        except ValueError:
            print(f"--since must be YYYY-MM-DD, got {args.since!r}")
            return 2

    tenant_id = await _resolve_tenant(args.tenant)
    DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
    pipeline = IngestionPipeline(tenant_id)

    started = datetime.now(UTC)
    ok = skipped = failed = 0

    async with httpx.AsyncClient(
        headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/json,*/*"},
        timeout=httpx.Timeout(120.0, connect=15.0),
    ) as http:
        if not args.skip_robots and not await _check_robots(http):
            return 1

        decisions = await _crawl_search(
            http,
            max_pages=args.max_pages,
            since=since,
            rate_sleep=args.rate,
        )

        if args.limit:
            decisions = decisions[: args.limit]

        if args.dry_run:
            print(f"Would ingest {len(decisions)} FOS decisions:")
            for d in decisions[:20]:
                print(
                    f"  {d.drn}  {(d.date_published or '?')!s:<11}  "
                    f"{(d.outcome or '?'):<18}  {(d.business or '?')}"
                )
            if len(decisions) > 20:
                print(f"  ... and {len(decisions) - 20} more")
            return 0

        for i, d in enumerate(decisions, 1):
            print(
                f"[{i}/{len(decisions)}] {d.drn}  "
                f"{(d.outcome or '?'):<18}  {(d.business or '?')}"
            )
            status, detail = await _ingest_decision(
                d, pipeline=pipeline, http=http, force=args.force
            )
            print(f"   → {status}: {detail}")
            if status == "ok":
                ok += 1
            elif status == "skipped":
                skipped += 1
            else:
                failed += 1
            await asyncio.sleep(args.rate)

    duration = (datetime.now(UTC) - started).total_seconds()
    print(
        f"\nDone in {duration:.1f}s. "
        f"Ingested={ok}  Skipped={skipped}  Failed={failed}"
    )
    return 0 if ok + skipped > 0 or args.dry_run else 1


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="fos_ingester",
        description="Bulk-ingest Financial Ombudsman Service final decisions.",
    )
    p.add_argument(
        "--tenant",
        default=DEFAULT_TENANT_SLUG,
        help=f"Tenant slug (default: {DEFAULT_TENANT_SLUG}).",
    )
    p.add_argument(
        "--max-pages",
        type=int,
        default=50,
        help="Max search pages to walk (default: 50 ≈ 500 decisions).",
    )
    p.add_argument(
        "--since",
        help="Only ingest decisions on or after this date (YYYY-MM-DD).",
    )
    p.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Stop after N decisions (0 = no limit). Useful for smoke tests.",
    )
    p.add_argument(
        "--rate",
        type=float,
        default=1.0,
        help="Seconds to sleep between HTTP requests (default: 1.0).",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="List the decisions that would be ingested and exit.",
    )
    p.add_argument(
        "--force",
        action="store_true",
        help="Re-download PDFs even if cached on disk.",
    )
    p.add_argument(
        "--skip-robots",
        action="store_true",
        help="Skip the robots.txt check (NOT recommended in production).",
    )
    p.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress per-fetch logs.",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    return asyncio.run(main_async(args))


# ---------------------------------------------------------------------------
# Programmatic entry point (used by the scheduled watcher task)
# ---------------------------------------------------------------------------


async def run_incremental(
    *,
    tenant_slug: str = DEFAULT_TENANT_SLUG,
    max_pages: int = 10,
    rate: float = 1.0,
) -> int:
    """Incremental FOS poll. Resolves the most-recent fos_date already in
    the DB and only ingests decisions newer than that. Designed to be
    called from a Celery beat task once a day.
    """
    sm = get_sessionmaker()
    async with sm() as session:
        # Look up the most recent fos_date in the demo-public tenant.
        # Stored in documents.metadata->>'fos_date' (ISO string).
        from sqlalchemy import text as sql_text

        row = await session.execute(
            sql_text(
                """
                SELECT MAX((metadata->>'fos_date')::date) AS max_date
                FROM documents d
                JOIN tenants t ON t.id = d.tenant_id
                WHERE t.slug = :slug
                  AND d.doc_type = 'fos-decision'
                  AND metadata ? 'fos_date'
                """
            ),
            {"slug": tenant_slug},
        )
        latest = row.scalar()
    since_str = latest.isoformat() if latest else None
    log.info("FOS incremental: since=%s, max_pages=%d", since_str or "(no prior)", max_pages)

    argv = ["--tenant", tenant_slug, "--max-pages", str(max_pages), "--rate", str(rate)]
    if since_str:
        argv += ["--since", since_str]
    return await main_async(_build_parser().parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
