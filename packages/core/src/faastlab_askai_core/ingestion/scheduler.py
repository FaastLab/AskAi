"""Indexer scheduling + folder helpers (pure — no DB/IO, so easily tested).

These back the "folder data source on a schedule" demo flow:
- `folder_prefix` decides where a folder Source's uploaded files live in object
  storage (one prefix per source, so sources never see each other's files).
- `is_indexer_due` is the scheduler's decision: given an indexer's `schedule`
  JSON and when it last ran, should the periodic beat tick run it now?
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

# Object-storage prefix under which a folder Source's files are stored. Kept in
# its own namespace ("datasources/<id>/") so uploads, listing, and the indexer
# crawl all agree on one location and sources stay isolated from each other and
# from regular document uploads.
_DATASOURCE_ROOT = "datasources"


def folder_prefix(source_id: UUID | str) -> str:
    """The storage key prefix (the "folder") for a folder-type Source."""
    return f"{_DATASOURCE_ROOT}/{source_id}/"


def storage_key_for(source_id: UUID | str, filename: str) -> str:
    """Full storage key for one uploaded file inside a folder Source.

    The filename is reduced to its basename so a client can't write outside the
    source's prefix via a crafted path (e.g. "../other/x").
    """
    safe_name = filename.replace("\\", "/").rsplit("/", 1)[-1].strip() or "file"
    return f"{folder_prefix(source_id)}{safe_name}"


def schedule_interval_minutes(schedule: dict | None) -> int | None:
    """Extract a positive interval (minutes) from an indexer `schedule` JSON, or
    None if the indexer isn't on a timed schedule."""
    if not schedule:
        return None
    raw = schedule.get("interval_minutes")
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    # A non-positive interval means "no schedule" rather than "run constantly".
    return value if value > 0 else None


def is_indexer_due(
    *,
    enabled: bool,
    schedule: dict | None,
    last_run_at: datetime | None,
    now: datetime,
) -> bool:
    """Whether the periodic beat should enqueue this indexer now.

    Rules (deterministic so it unit-tests without a clock):
    - disabled or no timed schedule  -> never due (manual "Run now" only);
    - never run before               -> due immediately (first scheduled run);
    - otherwise                      -> due once `interval` has elapsed since
                                        the last run.
    """
    if not enabled:
        return False
    interval = schedule_interval_minutes(schedule)
    if interval is None:
        return False
    if last_run_at is None:
        return True
    elapsed_seconds = (now - last_run_at).total_seconds()
    return elapsed_seconds >= interval * 60
