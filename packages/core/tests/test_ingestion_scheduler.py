"""Unit tests for the indexer scheduler + folder helpers (pure, no DB/clock)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from faastlab_askai_core.ingestion.scheduler import (
    folder_prefix,
    is_indexer_due,
    schedule_interval_minutes,
    storage_key_for,
)

_SID = UUID("11111111-1111-1111-1111-111111111111")
_NOW = datetime(2026, 6, 12, 12, 0, 0, tzinfo=UTC)


# ---- folder prefix / key safety --------------------------------------------


def test_folder_prefix_is_per_source() -> None:
    assert folder_prefix(_SID) == f"datasources/{_SID}/"


def test_storage_key_strips_path_traversal() -> None:
    # A crafted filename can't escape the source's prefix.
    assert storage_key_for(_SID, "../../etc/passwd") == f"datasources/{_SID}/passwd"
    assert storage_key_for(_SID, "docs\\spec.pdf") == f"datasources/{_SID}/spec.pdf"
    assert storage_key_for(_SID, "report.pdf") == f"datasources/{_SID}/report.pdf"


def test_storage_key_blank_filename_falls_back() -> None:
    assert storage_key_for(_SID, "   ") == f"datasources/{_SID}/file"


# ---- schedule interval parsing ---------------------------------------------


def test_schedule_interval_minutes() -> None:
    assert schedule_interval_minutes(None) is None
    assert schedule_interval_minutes({}) is None
    assert schedule_interval_minutes({"interval_minutes": 0}) is None  # 0 = manual
    assert schedule_interval_minutes({"interval_minutes": "bad"}) is None
    assert schedule_interval_minutes({"interval_minutes": 15}) == 15


# ---- is_indexer_due --------------------------------------------------------


def test_disabled_never_due() -> None:
    assert is_indexer_due(
        enabled=False, schedule={"interval_minutes": 5}, last_run_at=None, now=_NOW
    ) is False


def test_no_schedule_never_due() -> None:
    assert is_indexer_due(enabled=True, schedule={}, last_run_at=None, now=_NOW) is False


def test_never_run_is_due_immediately() -> None:
    assert is_indexer_due(
        enabled=True, schedule={"interval_minutes": 5}, last_run_at=None, now=_NOW
    ) is True


def test_due_only_after_interval_elapses() -> None:
    sched = {"interval_minutes": 10}
    # 9 minutes since last run -> not yet.
    assert is_indexer_due(
        enabled=True, schedule=sched, last_run_at=_NOW - timedelta(minutes=9), now=_NOW
    ) is False
    # 10 minutes -> due.
    assert is_indexer_due(
        enabled=True, schedule=sched, last_run_at=_NOW - timedelta(minutes=10), now=_NOW
    ) is True
