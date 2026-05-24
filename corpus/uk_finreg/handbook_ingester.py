"""Bulk regulator-handbook ingester.

Reads `handbook_sources.yaml`, downloads each item, and pushes through
the standard `IngestionPipeline` into the `demo-public` tenant (so all
signed-in Pro tenants inherit it via the shared-corpus union).

Two entry types are supported:

  - `pdf` — direct fetch of a single document (PDF / DOCX / HTML).
  - `govuk_manual` — recurses gov.uk's content API to collect every
    chapter of a multi-part manual (HMRC manuals especially), ingesting
    each chapter as its own document. Content API docs:
    https://content-api.publishing.service.gov.uk/

Design choices:

- **Sequential by default** — predictable OpenAI burn, plays nice with
  regulator rate limits. Override with `--max-concurrency`.
- **Idempotent** — the pipeline dedupes on `content_hash`, so re-running
  after a partial failure just resumes.
- **Per-item failures are warnings, not fatal** — a 404 on one PDF
  shouldn't abort the run. Final summary tallies success / skip / fail.
- **Honours OGL / Crown Copyright** — each document records its source
  URL on the `documents` row so attribution flows through to citations.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
import yaml
from sqlalchemy import select, update

from faastlab_askai_core.db import Document, Tenant, get_sessionmaker
from faastlab_askai_indexing.connectors.base import SourceDocument
from faastlab_askai_indexing.parsers.router import detect_content_type
from faastlab_askai_indexing.pipeline import IngestionPipeline

log = logging.getLogger(__name__)

CORPUS_DIR = Path(__file__).resolve().parent
DEFAULT_SOURCES_YAML = CORPUS_DIR / "handbook_sources.yaml"
DOWNLOADS_DIR = CORPUS_DIR / "_downloads" / "handbook"
DEFAULT_TENANT_SLUG = "demo-public"
USER_AGENT = "FaastLab-AskAi-HandbookIngester/0.1 (+https://faastlab.ai)"
GOVUK_API_BASE = "https://www.gov.uk/api/content"

# Minimum visible-text length (post HTML strip) for a gov.uk manual leaf
# page to be ingested. Below this, we treat the page as a stub title/
# navigation entry rather than substantive guidance. ~200 chars ≈ 30-40
# words, enough to filter "Glossary" / "Works of art" / etc. while
# keeping short-but-real definitions.
GOVUK_MIN_LEAF_CHARS = 200


# ---------------------------------------------------------------------------
# Tenant + sources
# ---------------------------------------------------------------------------


async def _resolve_tenant(slug: str) -> UUID:
    sm = get_sessionmaker()
    async with sm() as session:
        result = await session.execute(select(Tenant.id).where(Tenant.slug == slug))
        row = result.scalar_one_or_none()
    if row is None:
        raise SystemExit(f"Tenant {slug!r} not found — run `make migrate` first?")
    return row


def _load_sources(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    return list(data.get("ingests", []))


# ---------------------------------------------------------------------------
# gov.uk Content API — recursive crawler for multi-chapter manuals
# ---------------------------------------------------------------------------


async def _fetch_govuk(
    client: httpx.AsyncClient, path: str
) -> dict[str, Any] | None:
    """Fetch one node from gov.uk's content API. Returns parsed JSON or None."""
    url = GOVUK_API_BASE + path
    try:
        response = await client.get(url)
        response.raise_for_status()
        return response.json()
    except (httpx.HTTPError, json.JSONDecodeError) as exc:
        log.warning("govuk: failed to fetch %s: %s", path, exc)
        return None


def _govuk_child_paths(
    node: dict[str, Any],
) -> list[tuple[str, str | None, str | None]]:
    """Extract child-section paths from a gov.uk Content API node.

    gov.uk uses two different structures for multi-page content:
      1. HMRC Internal Manuals store children under
         `details.child_section_groups[].child_sections[]`.
      2. Generic guidance puts them under `links.child_sections` or
         `links.sections`.

    Returns (base_path, title, description) tuples — or [] if leaf.
    """
    out: list[tuple[str, str | None, str | None]] = []

    details = node.get("details") or {}
    for group in details.get("child_section_groups") or []:
        for sec in (group or {}).get("child_sections") or []:
            base_path = sec.get("base_path")
            if base_path:
                out.append(
                    (base_path, sec.get("title"), sec.get("description"))
                )

    if not out:
        for sec in (
            (node.get("links") or {}).get("child_sections")
            or (node.get("links") or {}).get("sections")
            or []
        ):
            base_path = sec.get("base_path")
            if base_path:
                out.append(
                    (base_path, sec.get("title"), sec.get("description"))
                )

    return out


async def _crawl_govuk_manual(
    client: httpx.AsyncClient,
    root_path: str,
    *,
    max_depth: int = 6,
) -> list[dict[str, str]]:
    """Recursively walk a gov.uk manual, returning one entry per LEAF page.

    HMRC manuals (cryptoassets-manual, ECSH, SAO, etc.) are nested:
    manual → chapter → section → rule page. The earlier implementation
    only fetched one level deep, so we collected chapter INDEX pages
    (containing only short descriptions) instead of the actual rule
    text. This recurses until we hit a leaf (no further child_sections),
    then emits that leaf's body.

    Cycle-safe via `visited`; bounded by `max_depth` to keep runaway
    structures from melting the OpenAI bill if gov.uk ever introduces a
    pathological loop.
    """
    leaves: list[dict[str, str]] = []
    visited: set[str] = set()
    await _walk_govuk(client, root_path, leaves, visited, 0, max_depth)
    return leaves


async def _walk_govuk(
    client: httpx.AsyncClient,
    path: str,
    out: list[dict[str, str]],
    visited: set[str],
    depth: int,
    max_depth: int,
) -> None:
    """One step of the recursive walk. Mutates `out` and `visited`."""
    if path in visited:
        return
    visited.add(path)
    if depth > max_depth:
        log.warning("govuk: hit max_depth=%d at %s — stopping branch", max_depth, path)
        return

    node = await _fetch_govuk(client, path)
    if node is None:
        return

    children = _govuk_child_paths(node)

    if children:
        log.info(
            "govuk: %s has %d child sections (depth=%d) — recursing",
            path, len(children), depth,
        )
        for child_path, _, _ in children:
            await _walk_govuk(client, child_path, out, visited, depth + 1, max_depth)
        return

    # Leaf: emit its body, but only if it has substantive text.
    body = (node.get("details") or {}).get("body") or ""
    if not body:
        log.warning("govuk: %s is a leaf with no body — skipping", path)
        return

    # HMRC manuals have many title-only stub pages (e.g. "Glossary",
    # "Ongoing monitoring") whose bodies render to <20 chars of visible
    # text. Indexing them pollutes search results with empty hits and
    # bloats the corpus. Strip HTML and require a minimum body length.
    text_only = re.sub(r"<[^>]+>", " ", body)
    text_only = re.sub(r"\s+", " ", text_only).strip()
    if len(text_only) < GOVUK_MIN_LEAF_CHARS:
        log.info(
            "govuk: %s leaf too thin (%d chars text after HTML strip) — skipping",
            path, len(text_only),
        )
        return

    title = node.get("title") or path
    out.append(
        {
            "title": title,
            "url": "https://www.gov.uk" + path,
            "html": _wrap_html(body, title),
        }
    )


def _wrap_html(body: str, title: str) -> str:
    """Wrap raw body HTML so the HtmlParser has a stable document."""
    return (
        "<!doctype html>"
        f"<html><head><meta charset='utf-8'><title>{title}</title></head>"
        f"<body><h1>{title}</h1>{body}</body></html>"
    )


# ---------------------------------------------------------------------------
# PDF download helper (cached on disk so re-runs are cheap)
# ---------------------------------------------------------------------------


async def _download(
    client: httpx.AsyncClient, url: str, *, dest: Path, force: bool
) -> Path | None:
    """Fetch `url` to `dest`. Detects soft-404s by checking the response
    content against the URL extension (PDFs must start with `%PDF-`).

    Returns None on transport error OR on soft-404 (200 OK but wrong type).
    """
    if dest.exists() and dest.stat().st_size > 0 and not force:
        log.info("cached: %s", dest.name)
        return dest
    log.info("fetch: %s", url)
    try:
        response = await client.get(url, follow_redirects=True)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        log.warning("download failed: %s (%s)", url, exc)
        return None

    body = response.content

    # Soft-404 detection — many regulator sites return 200 OK for missing
    # PDFs but serve the "page not found" HTML page in the body. Without
    # this check, the ingester happily indexes those error pages as
    # regulator content.
    looks_like_pdf_url = url.lower().split("?")[0].endswith(".pdf")
    starts_with_pdf_magic = body.startswith(b"%PDF-")
    content_type = response.headers.get("Content-Type", "").lower()
    if looks_like_pdf_url and not starts_with_pdf_magic:
        log.warning(
            "soft-404: %s returned 200 but body is not a PDF (Content-Type=%r, first 80 bytes=%r) — skipping",
            url,
            content_type,
            body[:80],
        )
        return None

    # For non-PDF URLs (HTML hubs), a tiny body is suspicious. Real
    # regulator pages are at least ~2 KB.
    if not looks_like_pdf_url and len(body) < 500:
        log.warning(
            "soft-404 (small body): %s returned %d bytes — skipping",
            url, len(body),
        )
        return None

    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(body)
    return dest


def _safe_filename(url: str) -> str:
    last = url.rsplit("/", 1)[-1].split("?")[0] or "download"
    # Keep filenames sane on Windows/Linux.
    return "".join(c if c.isalnum() or c in "._-" else "_" for c in last)[:120]


# ---------------------------------------------------------------------------
# Ingestion per item
# ---------------------------------------------------------------------------


async def _ingest_pdf_item(
    item: dict[str, Any],
    *,
    pipeline: IngestionPipeline,
    http: httpx.AsyncClient,
    force: bool,
) -> tuple[str, str]:
    url = item["url"]
    name = item.get("name") or url
    filename = _safe_filename(url)
    dest = DOWNLOADS_DIR / filename

    fetched = await _download(http, url, dest=dest, force=force)
    if fetched is None:
        return "failed", f"download failed: {url}"

    data = fetched.read_bytes()
    if not data:
        return "failed", "empty download"

    source = SourceDocument(
        source_uri=url,
        data=data,
        filename=filename,
        content_type=detect_content_type(filename, default="application/pdf"),
        title=name,
        metadata={
            "regulator": item.get("regulator"),
            "doc_type": item.get("doc_type"),
            "ogl_attribution": (
                "Contains public sector information licensed under the "
                "Open Government Licence v3.0 / Crown Copyright."
            ),
            "source": "handbook_ingester",
        },
    )

    try:
        result = await pipeline.ingest_one(source)
    except Exception as exc:  # noqa: BLE001 — we want to keep going on failures
        log.exception("ingest failed: %s", name)
        return "failed", f"ingest failed: {exc}"

    if result.skipped and result.note.startswith("error:"):
        return "failed", result.note
    if result.skipped:
        return "skipped", result.note or "already current"
    return "ok", f"{result.chunks_written} chunks"


async def _ingest_govuk_manual_item(
    item: dict[str, Any],
    *,
    pipeline: IngestionPipeline,
    http: httpx.AsyncClient,
) -> list[tuple[str, str, str]]:
    """Ingest one gov.uk manual = many chapters. Returns per-chapter status."""
    govuk_path = item.get("govuk_path") or ""
    if not govuk_path:
        return [("failed", item.get("name", "?"), "missing govuk_path")]

    chapters = await _crawl_govuk_manual(http, govuk_path)
    if not chapters:
        return [("failed", item.get("name", govuk_path), "no chapters fetched")]

    results: list[tuple[str, str, str]] = []
    for ch in chapters:
        source = SourceDocument(
            source_uri=ch["url"],
            data=ch["html"].encode("utf-8"),
            filename=_safe_filename(ch["url"]) + ".html",
            content_type="text/html",
            title=ch["title"],
            metadata={
                "regulator": item.get("regulator"),
                "doc_type": item.get("doc_type"),
                "manual": item.get("name"),
                "ogl_attribution": (
                    "Contains public sector information licensed under the "
                    "Open Government Licence v3.0."
                ),
                "source": "handbook_ingester",
            },
        )
        try:
            result = await pipeline.ingest_one(source)
        except Exception as exc:  # noqa: BLE001
            log.exception("chapter ingest failed: %s", ch["title"])
            results.append(("failed", ch["title"], f"ingest failed: {exc}"))
            continue
        if result.skipped and result.note.startswith("error:"):
            results.append(("failed", ch["title"], result.note))
        elif result.skipped:
            results.append(("skipped", ch["title"], result.note or "already current"))
        else:
            results.append(("ok", ch["title"], f"{result.chunks_written} chunks"))
    return results


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def main_async(args: argparse.Namespace) -> int:
    logging.basicConfig(
        level=logging.WARNING if args.quiet else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        force=True,
    )
    tenant_id = await _resolve_tenant(args.tenant)

    sources_path = Path(args.sources) if args.sources else DEFAULT_SOURCES_YAML
    items = _load_sources(sources_path)
    if not items:
        print(f"No ingests defined in {sources_path}")
        return 1

    if args.regulator:
        wanted = {r.lower().strip() for r in args.regulator}
        items = [
            i for i in items
            if (i.get("regulator") or "").lower() in wanted
        ]
        if not items:
            print(f"No ingests match --regulator {args.regulator}")
            return 1

    if args.dry_run:
        print(f"Would ingest {len(items)} items into tenant {args.tenant}:")
        for i in items:
            print(f"  [{i['type']:<14}] {i.get('regulator','?'):<6}  {i['name']}")
        return 0

    DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
    pipeline = IngestionPipeline(tenant_id)

    ok = skipped = failed = 0
    started = datetime.now(UTC)

    async with httpx.AsyncClient(
        headers={"User-Agent": USER_AGENT, "Accept": "application/json, */*"},
        timeout=httpx.Timeout(120.0, connect=15.0),
    ) as http:
        for i, item in enumerate(items, 1):
            name = item.get("name", "?")
            print(f"[{i}/{len(items)}] {item.get('regulator','?').upper()} · {name}")
            kind = item.get("type", "pdf")
            try:
                if kind == "pdf":
                    status, detail = await _ingest_pdf_item(
                        item, pipeline=pipeline, http=http, force=args.force
                    )
                    print(f"   → {status}: {detail}")
                    if status == "ok":
                        ok += 1
                        await _patch_doc(
                            tenant_id, item["url"], item.get("doc_type")
                        )
                    elif status == "skipped":
                        skipped += 1
                    else:
                        failed += 1
                elif kind == "govuk_manual":
                    rows = await _ingest_govuk_manual_item(
                        item, pipeline=pipeline, http=http
                    )
                    chap_ok = sum(1 for s, _, _ in rows if s == "ok")
                    chap_skip = sum(1 for s, _, _ in rows if s == "skipped")
                    chap_fail = sum(1 for s, _, _ in rows if s == "failed")
                    print(
                        f"   → {len(rows)} chapter(s): "
                        f"ok={chap_ok}, skipped={chap_skip}, failed={chap_fail}"
                    )
                    ok += chap_ok
                    skipped += chap_skip
                    failed += chap_fail
                else:
                    print(f"   → failed: unknown type {kind!r}")
                    failed += 1
            except Exception as exc:  # noqa: BLE001
                log.exception("item blew up: %s", name)
                print(f"   → failed: {exc}")
                failed += 1

    duration = (datetime.now(UTC) - started).total_seconds()
    print(
        f"\nDone in {duration:.1f}s. "
        f"Ingested={ok}  Skipped={skipped}  Failed={failed}"
    )
    return 0 if ok + skipped > 0 else 1


async def _patch_doc(
    tenant_id: UUID, source_uri: str, doc_type: str | None
) -> None:
    """Set doc_type on the row if the pipeline didn't (older docs)."""
    if not doc_type:
        return
    sm = get_sessionmaker()
    async with sm() as session:
        await session.execute(
            update(Document)
            .where(
                (Document.tenant_id == tenant_id)
                & (Document.source_uri == source_uri)
                & (Document.doc_type.is_(None))
            )
            .values(doc_type=doc_type.lower())
        )
        await session.commit()


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="handbook_ingester",
        description="Bulk-ingest UK regulator handbooks into the public corpus tenant.",
    )
    p.add_argument(
        "--tenant",
        default=DEFAULT_TENANT_SLUG,
        help=f"Tenant slug to ingest into (default: {DEFAULT_TENANT_SLUG}).",
    )
    p.add_argument(
        "--sources",
        default=None,
        help="Path to a YAML sources file (default: handbook_sources.yaml next to this script).",
    )
    p.add_argument(
        "--regulator",
        action="append",
        help="Limit to one regulator (e.g. --regulator fca). Repeatable.",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be ingested and exit.",
    )
    p.add_argument(
        "--force",
        action="store_true",
        help="Re-download even if a cached file exists on disk.",
    )
    p.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress per-fetch info logs (still prints the per-item summary).",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    sys.exit(main())
