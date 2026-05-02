"""Celery app — broker + result backend from settings."""

from __future__ import annotations

from celery import Celery

from faastlab_askai_core.config import get_settings


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
    return app


celery_app = make_celery()
