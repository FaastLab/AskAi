"""DB notifier — persists each new event to `watcher_events`.

Dedup is enforced by the unique `(regulator, external_id)` constraint;
on conflict we silently skip (idempotent re-poll).
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from faastlab_askai_core.db import Tenant, WatcherEvent, get_sessionmaker

from faastlab_askai_watcher.feeds.base import PublicationEvent
from faastlab_askai_watcher.notifications.base import Notifier

log = logging.getLogger("faastlab_askai.watcher")


class DBNotifier(Notifier):
    """Insert each new event into `watcher_events`."""

    name = "db"

    def __init__(self, *, tenant_slug: str) -> None:
        self._tenant_slug = tenant_slug
        self._tenant_id: UUID | None = None

    async def notify(self, events: Sequence[PublicationEvent]) -> None:
        if not events:
            return
        tenant_id = await self._resolve_tenant_id()
        if tenant_id is None:
            log.warning(
                "watcher: DBNotifier skipped %d events — tenant %r not found",
                len(events),
                self._tenant_slug,
            )
            return

        sm = get_sessionmaker()
        async with sm() as session:
            for ev in events:
                stmt = (
                    insert(WatcherEvent)
                    .values(
                        tenant_id=tenant_id,
                        regulator=ev.regulator,
                        event_type=ev.event_type,
                        external_id=ev.external_id,
                        title=ev.title,
                        url=ev.url,
                        published_at=ev.published_at,
                        summary=ev.summary,
                        payload=ev.payload,
                    )
                    .on_conflict_do_nothing(
                        constraint="uq_watcher_events_regulator_external"
                    )
                )
                await session.execute(stmt)
            await session.commit()

    async def _resolve_tenant_id(self) -> UUID | None:
        if self._tenant_id is not None:
            return self._tenant_id
        sm = get_sessionmaker()
        async with sm() as session:
            row = await session.execute(
                select(Tenant.id).where(Tenant.slug == self._tenant_slug)
            )
            value = row.scalar_one_or_none()
        if value is None:
            return None
        self._tenant_id = value
        return value
