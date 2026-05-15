"""Console notifier — logs each new publication at INFO level."""

from __future__ import annotations

import logging
from collections.abc import Sequence

from faastlab_askai_watcher.feeds.base import PublicationEvent
from faastlab_askai_watcher.notifications.base import Notifier

log = logging.getLogger("faastlab_askai.watcher")


class ConsoleNotifier(Notifier):
    name = "console"

    async def notify(self, events: Sequence[PublicationEvent]) -> None:
        for ev in events:
            log.info(
                "watcher: [%s] %s — %s",
                ev.regulator.upper(),
                ev.title,
                ev.url,
            )
