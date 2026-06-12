"""Celery app — broker + result backend from settings.

Scheduling needs a Celery **beat** process running against this app
(`celery -A faastlab_askai_indexing.celery_app beat`). Two periodic ticks:

- `run-due-indexers` (every 60s, always registered) — the ingestion-pipeline
  scheduler: enqueues any enabled Indexer whose schedule is due. This is what
  makes a folder data source index automatically. Harmless if no beat runs;
  manual "Run now" works regardless.
- `run-due-connectors` (opt-in via `CONNECTORS_SCHEDULER_ENABLED=true`) — the
  older JSONB web-connector scheduler.
"""

from __future__ import annotations

import os
from datetime import timedelta

from celery import Celery
from celery.schedules import schedule

from faastlab_askai_core.config import get_settings


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in ("1", "true", "yes", "on")


def make_celery() -> Celery:
    settings = get_settings()
    app = Celery(
        "faastlab_askai_indexing",
        broker=settings.celery_broker_url,
        backend=settings.celery_result_backend,
        include=["faastlab_askai_indexing.tasks"],
    )
    app.conf.update(
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        timezone="UTC",
        enable_utc=True,
        task_track_started=True,
        task_acks_late=True,
        worker_prefetch_multiplier=1,
    )
    # Periodic schedules (only fire if a beat process is running).
    beat: dict[str, dict] = {}

    # Always on: the ingestion-pipeline scheduler. Ticks every 60s and enqueues
    # indexers whose per-indexer interval has elapsed (the due-check is in
    # run_due_indexers). 60s is just how often we *check* — the indexer's own
    # interval_minutes decides how often it actually runs.
    indexer_tick = int(os.getenv("INDEXER_SCHEDULER_INTERVAL_SECONDS", "60"))
    beat["run-due-indexers"] = {
        "task": "askai.indexing.run_due_indexers",
        "schedule": schedule(run_every=timedelta(seconds=indexer_tick)),
    }

    # Opt-in: the older web-connector scheduler.
    if _truthy(os.getenv("CONNECTORS_SCHEDULER_ENABLED")):
        every = int(os.getenv("CONNECTORS_SCHEDULER_INTERVAL_SECONDS", "300"))
        beat["run-due-connectors"] = {
            "task": "askai.indexing.run_due_connectors",
            "schedule": schedule(run_every=timedelta(seconds=every)),
        }

    app.conf.beat_schedule = beat
    return app


celery_app = make_celery()
