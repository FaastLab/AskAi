"""Service-level test — dedup + notifier fan-out, with stubbed DB and feeds."""

from __future__ import annotations

from collections.abc import Sequence
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from faastlab_askai_watcher.feeds.base import FeedSource, PublicationEvent
from faastlab_askai_watcher.notifications.base import Notifier
from faastlab_askai_watcher.service import WatcherService


class _StubFeed:
    def __init__(self, regulator: str, events: list[PublicationEvent]) -> None:
        self.regulator = regulator
        self._events = events

    async def fetch(self, since=None) -> list[PublicationEvent]:  # noqa: ARG002
        return self._events


class _RecorderNotifier:
    def __init__(self) -> None:
        self.name = "recorder"
        self.calls: list[list[PublicationEvent]] = []

    async def notify(self, events: Sequence[PublicationEvent]) -> None:
        self.calls.append(list(events))


def _ev(reg: str, ext_id: str, title: str = "x") -> PublicationEvent:
    return PublicationEvent(
        regulator=reg,
        external_id=ext_id,
        title=title,
        url=f"https://example.org/{ext_id}",
    )


@pytest.mark.asyncio
async def test_poll_dedups_against_db() -> None:
    fca_feed = _StubFeed("fca", [_ev("fca", "a"), _ev("fca", "b")])
    boe_feed = _StubFeed("boe", [_ev("boe", "x")])
    notifier = _RecorderNotifier()

    service = WatcherService(
        feeds=[fca_feed, boe_feed],
        notifiers=[notifier],
    )

    # Stub out the DB lookup so 'fca/a' is "already known" and 'fca/b' + 'boe/x' are new.
    seen_rows = {("fca", "a")}

    class _FakeResult:
        def __init__(self, rows):
            self._rows = rows

        def all(self):  # noqa: D401
            return [(r,) for r in self._rows]

    async def _fake_execute(stmt):
        # Mimic the regulator-filtered IN clause: just return the
        # subset of `seen_rows` matching the stmt's parameters.
        compiled = str(stmt.compile(compile_kwargs={"literal_binds": True}))
        rows = []
        for reg, ext in seen_rows:
            if f"'{reg}'" in compiled and f"'{ext}'" in compiled:
                rows.append(ext)
        return _FakeResult(rows)

    fake_session = MagicMock()
    fake_session.__aenter__ = AsyncMock(return_value=fake_session)
    fake_session.__aexit__ = AsyncMock(return_value=False)
    fake_session.execute = AsyncMock(side_effect=_fake_execute)

    fake_sm = MagicMock(return_value=fake_session)

    with patch(
        "faastlab_askai_watcher.service.get_sessionmaker",
        return_value=fake_sm,
    ):
        outcome = await service.poll()

    assert outcome.fetched == 3
    assert outcome.new_events == 2  # 'a' was already seen
    # Notifier got the two NEW events:
    assert len(notifier.calls) == 1
    titles = sorted(e.external_id for e in notifier.calls[0])
    assert titles == ["b", "x"]


@pytest.mark.asyncio
async def test_feed_failure_does_not_break_others() -> None:
    good = _StubFeed("fca", [_ev("fca", "a")])

    class _AngryFeed:
        regulator = "boe"

        async def fetch(self, since=None):  # noqa: ARG002
            raise RuntimeError("regulator site down")

    notifier = _RecorderNotifier()
    service = WatcherService(feeds=[good, _AngryFeed()], notifiers=[notifier])

    fake_session = MagicMock()
    fake_session.__aenter__ = AsyncMock(return_value=fake_session)
    fake_session.__aexit__ = AsyncMock(return_value=False)

    class _FakeResult:
        def all(self):  # noqa: D401
            return []

    fake_session.execute = AsyncMock(return_value=_FakeResult())
    fake_sm = MagicMock(return_value=fake_session)

    with patch(
        "faastlab_askai_watcher.service.get_sessionmaker",
        return_value=fake_sm,
    ):
        outcome = await service.poll()

    # One feed crashed, the other delivered one new event:
    assert outcome.feeds_polled == 2
    assert outcome.feeds_errored == 1
    assert outcome.new_events == 1
    assert notifier.calls[0][0].external_id == "a"


def test_notifier_protocol_shape() -> None:
    # Compile-time-ish smoke: the recorder must satisfy the Notifier protocol.
    assert isinstance(_RecorderNotifier(), Notifier)


def test_feed_source_protocol_shape() -> None:
    feed = _StubFeed("fca", [])
    assert isinstance(feed, FeedSource)
