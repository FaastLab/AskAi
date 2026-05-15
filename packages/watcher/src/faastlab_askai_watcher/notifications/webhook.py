"""Generic HTTP webhook notifier — POSTs one JSON envelope per batch.

Customers configure `WATCHER_WEBHOOK_URL` to receive new-publication
events on any URL they own. We POST a single payload per poll cycle so
downstream systems can batch-handle. Per-event POSTs are deferred — most
ops teams want one alert per cycle, not 12.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import datetime, timezone

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from faastlab_askai_watcher.feeds.base import PublicationEvent
from faastlab_askai_watcher.notifications.base import Notifier

log = logging.getLogger("faastlab_askai.watcher")


class WebhookNotifier(Notifier):
    """POST a JSON envelope of new events to a configured URL."""

    name = "webhook"

    def __init__(
        self,
        url: str,
        *,
        timeout_seconds: float = 10.0,
        user_agent: str = "FaastLab-AskAi-Watcher/0.1 (+https://faastlab.ai)",
    ) -> None:
        if not url:
            raise ValueError("WebhookNotifier requires a non-empty URL")
        self._url = url
        self._timeout = httpx.Timeout(timeout_seconds)
        self._user_agent = user_agent

    async def notify(self, events: Sequence[PublicationEvent]) -> None:
        if not events:
            return
        body = {
            "version": "1",
            "source": "faastlab-askai-watcher",
            "emitted_at": datetime.now(timezone.utc).isoformat(),
            "event_count": len(events),
            "events": [
                {
                    "regulator": e.regulator,
                    "event_type": e.event_type,
                    "external_id": e.external_id,
                    "title": e.title,
                    "url": e.url,
                    "published_at": (
                        e.published_at.isoformat()
                        if e.published_at is not None
                        else None
                    ),
                    "summary": e.summary,
                }
                for e in events
            ],
        }
        try:
            await self._post(body)
        except Exception as exc:  # noqa: BLE001 — log + continue
            log.warning(
                "watcher: webhook to %s failed after retries: %s",
                self._url,
                exc,
            )

    @retry(
        retry=retry_if_exception_type(
            (httpx.HTTPError, httpx.TimeoutException)
        ),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    async def _post(self, body: dict) -> None:
        async with httpx.AsyncClient(
            timeout=self._timeout,
            headers={
                "User-Agent": self._user_agent,
                "Content-Type": "application/json",
            },
        ) as client:
            response = await client.post(self._url, json=body)
            response.raise_for_status()
