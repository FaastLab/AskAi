"""Feed protocol + DTO shared by every regulator adapter."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol, runtime_checkable


@dataclass(slots=True, frozen=True)
class PublicationEvent:
    """A single thing a regulator just published.

    `external_id` is whatever uniquely identifies this item in the
    regulator's own feed — typically the article URL, but some feeds
    provide a stable `<guid>` we'd rather use. Combined with `regulator`
    it forms the dedup key persisted to `watcher_events`.

    `event_type` is a coarse classifier — most items are publications,
    but FOS produces decisions, PRA produces consultations, etc. We don't
    enforce a vocabulary; downstream consumers can filter.

    `payload` carries the raw feed entry (after JSON-safe coercion) so
    auditors / debugging can see exactly what the regulator emitted.
    """

    regulator: str
    external_id: str
    title: str
    url: str
    published_at: datetime | None = None
    summary: str | None = None
    event_type: str = "publication"
    payload: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class FeedSource(Protocol):
    """A pollable source of regulator publications.

    Adapters MUST be idempotent: calling `fetch()` twice in a row with the
    same `since` should produce the same events. Deduplication against
    `watcher_events` happens upstream in the service.
    """

    regulator: str

    async def fetch(self, since: datetime | None = None) -> list[PublicationEvent]:
        """Return recent events from this regulator.

        `since` is a hint — adapters may use it to short-circuit, but the
        service still dedupes by `(regulator, external_id)` so a feed
        that returns the full window is safe (just less efficient).
        """
        ...
