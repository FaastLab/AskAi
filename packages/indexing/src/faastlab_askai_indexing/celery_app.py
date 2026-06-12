"""Celery app — broker + result backend from settings.

Connector scheduling (#8) is opt-in: set `CONNECTORS_SCHEDULER_ENABLED=true`
and run a Celery beat against this app to periodically enqueue due connectors.
Manual 'run now' (the API enqueueing `run_web_connector`) needs no beat.
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
    # Opt-in periodic scheduler: enqueue connectors whose interval is due.
    if _truthy(os.getenv("CONNECTORS_SCHEDULER_ENABLED")):
        every = int(os.getenv("CONNECTORS_SCHEDULER_INTERVAL_SECONDS", "300"))
        app.conf.beat_schedule = {
            "run-due-connectors": {
                "task": "askai.indexing.run_due_connectors",
                "schedule": schedule(run_every=timedelta(seconds=every)),
            }
        }
    return app


celery_app = make_celery()
