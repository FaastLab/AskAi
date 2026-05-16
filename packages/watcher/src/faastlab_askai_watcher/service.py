"""WatcherService — orchestrates feed polling + dedup + notification.

Flow per poll:
1. For each `FeedSource`, fetch recent events (per-feed try/except so one
   regulator down doesn't kill the others).
2. Dedup against `watcher_events.(regulator, external_id)`.
3. Fan-out genuinely new events to every configured notifier.

This service is invoked from Celery Beat (`tasks.py`) on a schedule, and
from `cli.py` for one-shot manual polls.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from faastlab_askai_core.config import get_settings
from faastlab_askai_core.db import WatcherEvent, get_sessionmaker

from faastlab_askai_watcher.feeds.base import FeedSource, PublicationEvent
from faastlab_askai_watcher.feeds.registry import default_feeds, filter_feeds
from faastlab_askai_watcher.notifications import (
    ConsoleNotifier,
    DBNotifier,
    IngestNotifier,
    Notifier,
    WebhookNotifier,
)

log = logging.getLogger("faastlab_askai.watcher")


@dataclass
class PollOutcome:
    """Result of one poll cycle — useful for the CLI and metrics later."""

    polled_at: datetime
    duration_seconds: float
    feeds_polled: int = 0
    feeds_errored: int = 0
    fetched: int = 0
    new_events: int = 0
    notifiers_run: int = 0
    notifier_errors: int = 0
    per_regulator: dict[str, int] = field(default_factory=dict)


class WatcherService:
    """Orchestrator. Inject feeds + notifiers, or let it build defaults."""

    def __init__(
        self,
        *,
        feeds: Sequence[FeedSource] | None = None,
        notifiers: Sequence[Notifier] | None = None,
    ) -> None:
        self._feeds: list[FeedSource] = list(feeds) if feeds is not None else default_feeds()
        self._notifiers: list[Notifier] = (
            list(notifiers) if notifiers is not None else self._build_default_notifiers()
        )

    async def poll(
        self,
        *,
        only: list[str] | None = None,
        since_hours: int | None = None,
    ) -> PollOutcome:
        """Run one full poll cycle. Returns a summary outcome."""
        started = datetime.now(timezone.utc)
        outcome = PollOutcome(polled_at=started, duration_seconds=0.0)

        since = (
            started - timedelta(hours=since_hours) if since_hours is not None else None
        )

        feeds = filter_feeds(self._feeds, only=only)
        outcome.feeds_polled = len(feeds)

        all_fetched: list[PublicationEvent] = []
        for feed in feeds:
            try:
                events = await feed.fetch(since)
            except Exception as exc:  # noqa: BLE001 — keep polling the others
                log.exception("watcher: %s feed raised: %s", feed.regulator, exc)
                outcome.feeds_errored += 1
                continue
            log.info("watcher: fetched %d entries from %s", len(events), feed.regulator)
            all_fetched.extend(events)

        outcome.fetched = len(all_fetched)

        # Dedup before sending to any notifier — one DB round-trip per
        # poll, regardless of feed count.
        new_events = await self._filter_new(all_fetched)
        outcome.new_events = len(new_events)
        for ev in new_events:
            outcome.per_regulator[ev.regulator] = (
                outcome.per_regulator.get(ev.regulator, 0) + 1
            )

        # Fan out — every notifier sees every new event. DBNotifier is
        # idempotent via ON CONFLICT, so the order doesn't matter.
        if new_events:
            for notifier in self._notifiers:
                outcome.notifiers_run += 1
                try:
                    await notifier.notify(new_events)
                except Exception as exc:  # noqa: BLE001
                    log.exception(
                        "watcher: notifier %s failed: %s", notifier.name, exc
                    )
                    outcome.notifier_errors += 1

        ended = datetime.now(timezone.utc)
        outcome.duration_seconds = (ended - started).total_seconds()
        log.info(
            "watcher: poll done in %.1fs — %d fetched, %d new across %d regulators",
            outcome.duration_seconds,
            outcome.fetched,
            outcome.new_events,
            len(outcome.per_regulator),
        )
        return outcome

    # ---- helpers ---------------------------------------------------------

    async def _filter_new(
        self, events: Sequence[PublicationEvent]
    ) -> list[PublicationEvent]:
        """Drop events that already exist in `watcher_events`."""
        if not events:
            return []

        # Group by regulator to make the lookup cheap (one IN-clause per
        # regulator). Five small queries beat one 500-row IN-clause.
        by_reg: dict[str, list[PublicationEvent]] = {}
        for ev in events:
            by_reg.setdefault(ev.regulator, []).append(ev)

        sm = get_sessionmaker()
        new: list[PublicationEvent] = []
        async with sm() as session:
            for regulator, group in by_reg.items():
                ids = [e.external_id for e in group]
                rows = await session.execute(
                    select(WatcherEvent.external_id).where(
                        (WatcherEvent.regulator == regulator)
                        & (WatcherEvent.external_id.in_(ids))
                    )
                )
                seen = {row[0] for row in rows.all()}
                for ev in group:
                    if ev.external_id not in seen:
                        new.append(ev)
        return new

    def _build_default_notifiers(self) -> list[Notifier]:
        settings = get_settings()
        notifiers: list[Notifier] = [
            ConsoleNotifier(),
            DBNotifier(tenant_slug=settings.watcher_tenant_slug),
        ]
        # IngestNotifier runs AFTER DBNotifier so the row exists when we
        # come back to mark it `ingested=true`. Opt-in: most users want
        # to inspect events before letting the pipeline crawl the URLs.
        if settings.watcher_auto_ingest:
            notifiers.append(
                IngestNotifier(
                    tenant_slug=settings.watcher_tenant_slug,
                    user_agent=settings.watcher_user_agent,
                )
            )
        if settings.watcher_webhook_url:
            notifiers.append(
                WebhookNotifier(
                    settings.watcher_webhook_url,
                    user_agent=settings.watcher_user_agent,
                )
            )
        return notifiers
