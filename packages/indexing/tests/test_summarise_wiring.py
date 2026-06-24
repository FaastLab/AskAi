"""Guards for the post-ingest summarisation wiring.

The auto-summarise feature depends on two easily-broken links: the worker's
Celery app must `include` the summarisation tasks module, and the
`summarise_on_ingest` setting must exist. These tests fail loudly if either
regresses.
"""

from __future__ import annotations

from faastlab_askai_core.config import get_settings
from faastlab_askai_indexing.celery_app import celery_app


def test_worker_includes_summarisation_tasks() -> None:
    # Without this include, the worker never registers the summary task, so
    # enqueued jobs would sit unrun.
    assert "faastlab_askai_summarisation.tasks" in (celery_app.conf.include or [])


def test_summarise_task_registers_on_import() -> None:
    import faastlab_askai_summarisation.tasks  # noqa: F401 — registers via decorator

    assert "askai.summarisation.summarise_document" in celery_app.tasks


def test_summarise_on_ingest_setting_exists() -> None:
    # Defaults on; operators can set SUMMARISE_ON_INGEST=false to skip it.
    assert isinstance(get_settings().summarise_on_ingest, bool)
