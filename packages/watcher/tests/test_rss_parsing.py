"""RSS adapter tests — no network. We hand-feed a known feed body."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from faastlab_askai_watcher.feeds.rss import RssFeed

# A minimal but realistic RSS 2.0 document. Two items, both with link, title,
# and pubDate; one has a guid, the other will fall back to the link.
_FEED_BYTES = b"""<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <title>Test regulator</title>
    <link>https://example.org</link>
    <description>Test</description>
    <item>
      <title>Consultation paper CP1/26</title>
      <link>https://example.org/cp1</link>
      <guid isPermaLink="false">cp1-2026</guid>
      <pubDate>Mon, 04 May 2026 09:00:00 GMT</pubDate>
      <description>Proposed rules on consumer credit.</description>
    </item>
    <item>
      <title>Policy statement PS3/26</title>
      <link>https://example.org/ps3</link>
      <pubDate>Tue, 05 May 2026 11:00:00 GMT</pubDate>
    </item>
  </channel>
</rss>
"""


@pytest.mark.asyncio
async def test_fetch_maps_items_to_events() -> None:
    feed = RssFeed("test", "https://example.org/feed.rss")
    with patch.object(feed, "_fetch_raw", new=AsyncMock(return_value=_FEED_BYTES)):
        events = await feed.fetch()
    assert len(events) == 2
    assert events[0].regulator == "test"
    assert events[0].title == "Consultation paper CP1/26"
    assert events[0].url == "https://example.org/cp1"
    # guid (when present and non-permalink) should be preferred as external_id.
    assert events[0].external_id == "cp1-2026"
    # The second item has no guid, so the link wins.
    assert events[1].external_id == "https://example.org/ps3"


@pytest.mark.asyncio
async def test_fetch_filters_by_since() -> None:
    from datetime import datetime, timezone

    feed = RssFeed("test", "https://example.org/feed.rss")
    with patch.object(feed, "_fetch_raw", new=AsyncMock(return_value=_FEED_BYTES)):
        recent = await feed.fetch(
            since=datetime(2026, 5, 5, 0, 0, tzinfo=timezone.utc)
        )
    titles = [e.title for e in recent]
    assert titles == ["Policy statement PS3/26"]


@pytest.mark.asyncio
async def test_fetch_returns_empty_on_network_failure() -> None:
    feed = RssFeed("test", "https://example.org/feed.rss")
    with patch.object(
        feed, "_fetch_raw", new=AsyncMock(side_effect=RuntimeError("dns"))
    ):
        events = await feed.fetch()
    # We swallow + log so one bad feed doesn't kill the whole poll.
    assert events == []
