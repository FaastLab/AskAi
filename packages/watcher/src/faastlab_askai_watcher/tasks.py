"""Celery tasks for scheduled polling. Bridge to the async service."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from faastlab_askai_watcher.celery_app import celery_app
from faastlab_askai_watcher.service import WatcherService

log = logging.getLogger("faastlab_askai.watcher")


@celery_app.task(name="askai.watcher.poll")
def poll() -> dict[str, Any]:
    """Run one poll cycle. Returns a JSON-safe summary."""
    outcome = asyncio.run(WatcherService().poll())
    return {
        "polled_at": outcome.polled_at.isoformat(),
        "duration_seconds": outcome.duration_seconds,
        "feeds_polled": outcome.feeds_polled,
        "feeds_errored": outcome.feeds_errored,
        "fetched": outcome.fetched,
        "new_events": outcome.new_events,
        "notifiers_run": outcome.notifiers_run,
        "notifier_errors": outcome.notifier_errors,
        "per_regulator": outcome.per_regulator,
    }


@celery_app.task(name="askai.watcher.fos_ingest")
def fos_ingest() -> dict[str, Any]:
    """Incremental FOS final-decisions ingest. Picks up where the last
    run left off (most-recent fos_date already in DB) and pulls newer
    decisions only."""
    from faastlab_askai_core.config import get_settings

    # Lazy import — keeps the watcher worker startup light when
    # `corpus.uk_finreg` isn't available in some images.
    from corpus.uk_finreg.fos_ingester import run_incremental

    settings = get_settings()
    exit_code = asyncio.run(
        run_incremental(
            tenant_slug=settings.watcher_tenant_slug,
            max_pages=settings.fos_ingest_max_pages,
        )
    )
    return {"exit_code": exit_code}
