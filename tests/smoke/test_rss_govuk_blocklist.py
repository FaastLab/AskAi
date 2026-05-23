"""Watcher feed regression: gov.uk firehoses (HMRC/TPR/ICO) emit lots of
non-regulatory junk — statistics announcements, ministerial speeches,
press releases. These produced ~63 useless rows in the demo-public
corpus before we added URL filtering. This test pins the filter.
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from faastlab_askai_watcher.feeds.registry import GOVUK_NOISE_PATHS
from faastlab_askai_watcher.feeds.rss import RssFeed


# A synthetic feedparser-style result with both good and noise entries.
def _fake_parsed():
    def e(url: str, title: str) -> SimpleNamespace:
        return SimpleNamespace(
            link=url,
            title=title,
            id=url,
            published_parsed=(2026, 5, 1, 12, 0, 0, 0, 0, 0),
            summary="…",
            items=lambda: [],  # feedparser entries support .items()
        )

    # Need .entries iterable + .bozo + each entry supports .items() — patch
    # _entry_to_event via just iterating; feedparser-like dict access.
    entries = [
        # Bad — should be dropped
        e("https://www.gov.uk/government/statistics/uk-trade-nov-2026", "Stats noise"),
        e(
            "https://www.gov.uk/government/statistics/announcements/whatever-2026",
            "Stats announcement",
        ),
        e("https://www.gov.uk/government/news/some-press-release", "Press release"),
        e("https://www.gov.uk/government/speeches/chancellor-speech", "Speech"),
        e("https://www.gov.uk/government/people/permanent-secretary", "Person"),
        e("https://www.gov.uk/government/collections/some-index", "Collection"),
        # Good — should be kept
        e(
            "https://www.gov.uk/hmrc-internal-manuals/cryptoassets-manual/cryptoasset-1",
            "HMRC Cryptoassets manual update",
        ),
        e(
            "https://www.gov.uk/guidance/anti-money-laundering-guidance",
            "AML guidance update",
        ),
        e(
            "https://www.gov.uk/government/publications/consultation-on-fees",
            "Genuine publication",
        ),
    ]
    return SimpleNamespace(entries=entries, bozo=False, bozo_exception=None)


@pytest.mark.asyncio
async def test_govuk_blocklist_drops_noise_keeps_regulatory():
    feed = RssFeed(
        regulator="hmrc",
        url="https://example.invalid/hmrc.atom",
        exclude_url_substrings=GOVUK_NOISE_PATHS,
    )

    # Patch the network call + feedparser.parse so this test is hermetic.
    async def fake_fetch_raw(_self):
        return b"<irrelevant />"

    with patch.object(RssFeed, "_fetch_raw", new=fake_fetch_raw), patch(
        "faastlab_askai_watcher.feeds.rss.feedparser.parse",
        return_value=_fake_parsed(),
    ):
        events = await feed.fetch()

    urls = [e.url for e in events]
    # Noise dropped:
    for bad in (
        "/government/statistics/",
        "/government/news/",
        "/government/speeches/",
        "/government/people/",
        "/government/collections/",
    ):
        assert not any(bad in u for u in urls), f"noise leaked: {bad}"
    # Good kept:
    assert any("hmrc-internal-manuals" in u for u in urls)
    assert any("/guidance/" in u for u in urls)
    assert any("/government/publications/" in u for u in urls)
    assert len(events) == 3


def test_blocklist_is_case_insensitive():
    feed = RssFeed(
        regulator="hmrc",
        url="https://example.invalid",
        exclude_url_substrings=("/government/statistics/",),
    )
    assert feed._is_excluded(
        "https://www.GOV.uk/Government/Statistics/foo"
    ) is True
    assert feed._is_excluded("https://www.gov.uk/hmrc-internal-manuals/x") is False
