"""Celery app for the watcher — shares broker/backend with indexing.

Run as a separate worker / beat process, or merge with the indexing
worker via `--include=faastlab_askai_watcher.tasks` on the indexing
worker's command line.

Beat schedule is wired via settings (`WATCHER_POLL_INTERVAL_SECONDS`).
Set `WATCHER_ENABLED=false` to disable the scheduled task entirely
without removing the package from the worker image.
"""

from __future__ import annotations

from celery import Celery
from celery.schedules import schedule

from faastlab_askai_core.config import get_settings


def make_celery() -> Celery:
    settings = get_settings()
    app = Celery(
        "faastlab_askai_watcher",
        broker=settings.celery_broker_url,
        backend=settings.celery_result_backend,
        include=["faastlab_askai_watcher.tasks"],
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
    if settings.watcher_enabled:
        app.conf.beat_schedule = {
            "watcher-poll": {
                "task": "askai.watcher.poll",
                "schedule": schedule(
                    run_every=settings.watcher_poll_interval_seconds
                ),
                "options": {"expires": settings.watcher_poll_interval_seconds},
            }
        }
    return app


celery_app = make_celery()
