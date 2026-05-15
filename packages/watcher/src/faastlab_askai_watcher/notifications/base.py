"""Notifier protocol — every channel must implement `notify(events)`."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from faastlab_askai_watcher.feeds.base import PublicationEvent


@runtime_checkable
class Notifier(Protocol):
    """Side-effecting sink for new regulator events.

    Implementations MUST be safe to call with an empty list (no-op) and
    SHOULD swallow per-event errors rather than blowing up the whole
    batch — one flaky webhook shouldn't lose a publication that the DB
    notifier just successfully persisted.
    """

    name: str

    async def notify(self, events: Sequence[PublicationEvent]) -> None:
        """Fire side effects for each event in the batch."""
        ...
