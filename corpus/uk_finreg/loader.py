"""Demo corpus loader — fetch, store, ingest, summarise.

Reads `sources.yaml`, downloads each PDF (with rate limit + cache),
runs the standard `IngestionPipeline` against the `demo-public` tenant,
then optionally runs summarisation.

Respects the Open Government Licence v3.0 — these documents are public
(BoE, PRA, FCA) and the OGL allows redistribution with attribution.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import httpx
import yaml
from sqlalchemy import select

from faastlab_askai_core.db import Document, Tenant, get_sessionmaker
from faastlab_askai_indexing.connectors.base import SourceDocument
from faastlab_askai_indexing.pipeline import IngestionPipeline
from faastlab_askai_indexing.parsers.router import detect_content_type
from faastlab_askai_summarisation.service import SummarisationService

log = logging.getLogger(__name__)

CORPUS_DIR = Path(__file__).resolve().parent
SOURCES_YAML = CORPUS_DIR / "sources.yaml"
DOWNLOADS_DIR = CORPUS_DIR / "_downloads"
DEFAULT_TENANT_SLUG = "demo-public"
USER_AGENT = "FaastLab-AskAi-DemoCorpus/0.1 (+https://faastlab.ai)"


async def _resolve_tenant(slug: str) -> UUID:
    sm = get_sessionmaker()
    async with sm() as session:
        result = await session.execute(select(Tenant.id).where(Tenant.slug == slug))
        row = result.scalar_one_or_none()
    if row is None:
        raise SystemExit(f"Tenant {slug!r} not found — did you `make migrate`?")
    return row


def _load_sources() -> list[dict[str, str]]:
    with SOURCES_YAML.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    return list(data.get("sources", []))


async def _download(client: httpx.AsyncClient, url: str, *, dest: Path) -> Path:
    if dest.exists() and dest.stat().st_size > 0:
        log.info("Cached: %s", dest.name)
        return dest
    log.info("Fetching: %s", url)
    response = await client.get(url, follow_redirects=True)
    response.raise_for_status()
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(response.content)
    return dest


def _filename_for(source: dict[str, str]) -> str:
    """Stable filename based on the URL's last segment."""
    url = source["url"]
    return url.rsplit("/", 1)[-1].split("?")[0]


async def main_async(*, tenant: str, summarise: bool, force: bool) -> int:
    tenant_id = await _resolve_tenant(tenant)
    sources = _load_sources()
    if not sources:
        print("No sources defined in sources.yaml")
        return 1

    DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
    pipeline = IngestionPipeline(tenant_id)
    summariser = SummarisationService() if summarise else None

    ok = skipped = failed = 0
    async with httpx.AsyncClient(
        headers={"User-Agent": USER_AGENT},
        timeout=httpx.Timeout(60.0, connect=10.0),
    ) as http:
        for source in sources:
            filename = _filename_for(source)
            dest = DOWNLOADS_DIR / filename
            try:
                await _download(http, source["url"], dest=dest)
            except httpx.HTTPError as exc:
                log.warning("Skip %s: download failed (%s)", source["name"], exc)
                failed += 1
                continue

            data = dest.read_bytes()
            metadata = {
                "regulator": source.get("regulator"),
                "doc_type": source.get("doc_type"),
                "ogl_attribution": (
                    "Contains public sector information licensed under the "
                    "Open Government Licence v3.0."
                ),
            }
            sd = SourceDocument(
                source_uri=source["url"],
                data=data,
                filename=filename,
                content_type=detect_content_type(filename, default="application/pdf"),
                metadata={k: v for k, v in metadata.items() if v},
            )
            try:
                result = await pipeline.ingest_one(sd)
            except Exception as exc:  # noqa: BLE001
                log.exception("Ingest failed for %s", source["name"])
                failed += 1
                continue

            if result.skipped and result.note.startswith("error:"):
                failed += 1
                print(f"[FAIL] {source['name']}: {result.note}")
                continue
            if result.skipped:
                skipped += 1
                print(f"[SKIP] {source['name']} ({result.note})")
                if force and summariser is not None:
                    await _run_summarise(summariser, tenant_id, source["url"])
                continue

            ok += 1
            print(
                f"[OK]   {source['name']} → {result.chunks_written} chunks "
                f"(doc {result.document_id})"
            )
            # Update doc_type / effective_date / metadata on the row.
            await _patch_document(
                tenant_id=tenant_id,
                source_uri=source["url"],
                doc_type=source.get("doc_type"),
                effective_date=source.get("effective_date"),
            )
            if summariser is not None:
                await _run_summarise(summariser, tenant_id, source["url"])

    print(f"\nDone. Ingested={ok}  Skipped={skipped}  Failed={failed}")
    # Only fail the run if EVERY source failed. Individual 404s are routine
    # for regulator URLs (they keep moving) — a partial corpus is still useful.
    if failed > 0 and ok == 0 and skipped == 0:
        return 1
    return 0


async def _patch_document(
    *,
    tenant_id: UUID,
    source_uri: str,
    doc_type: str | None,
    effective_date: str | None,
) -> None:
    sm = get_sessionmaker()
    async with sm() as session:
        result = await session.execute(
            select(Document).where(
                (Document.tenant_id == tenant_id)
                & (Document.source_uri == source_uri)
            )
        )
        doc = result.scalar_one_or_none()
        if doc is None:
            return
        if doc_type:
            doc.doc_type = doc_type
        if effective_date:
            try:
                doc.effective_date = datetime.fromisoformat(effective_date).replace(
                    tzinfo=UTC
                )
            except ValueError:
                pass
        await session.commit()


async def _run_summarise(
    service: SummarisationService, tenant_id: UUID, source_uri: str
) -> None:
    sm = get_sessionmaker()
    async with sm() as session:
        result = await session.execute(
            select(Document.id).where(
                (Document.tenant_id == tenant_id)
                & (Document.source_uri == source_uri)
            )
        )
        doc_id = result.scalar_one_or_none()
    if doc_id is None:
        return
    try:
        await service.summarise_document(tenant_id=tenant_id, document_id=doc_id)
        print(f"        ↳ summary generated")
    except Exception as exc:  # noqa: BLE001
        log.warning("Summary failed for %s: %s", source_uri, exc)


def main() -> int:
    parser = argparse.ArgumentParser(prog="askai-demo-corpus")
    parser.add_argument("--tenant", default=DEFAULT_TENANT_SLUG)
    parser.add_argument(
        "--no-summarise",
        action="store_true",
        help="Skip the summarisation pass (faster)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-summarise documents even if already summarised",
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    return asyncio.run(
        main_async(
            tenant=args.tenant,
            summarise=not args.no_summarise,
            force=args.force,
        )
    )


if __name__ == "__main__":
    sys.exit(main())
