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
