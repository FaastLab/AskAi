"""CLI for one-shot polls and ad-hoc operations.

Usage:
    python -m faastlab_askai_watcher poll
    python -m faastlab_askai_watcher poll --regulator fca
    python -m faastlab_askai_watcher poll --regulator fca --regulator boe
    python -m faastlab_askai_watcher poll --since-hours 24
    python -m faastlab_askai_watcher list-feeds
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys

from faastlab_askai_watcher.feeds.registry import default_feeds
from faastlab_askai_watcher.service import WatcherService


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="faastlab_askai_watcher",
        description="Poll UK regulator feeds for new publications.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    poll = sub.add_parser("poll", help="Run one poll cycle and exit.")
    poll.add_argument(
        "--regulator",
        action="append",
        default=None,
        metavar="CODE",
        help="Limit to one regulator (repeat for multiple). Default: all.",
    )
    poll.add_argument(
        "--since-hours",
        type=int,
        default=None,
        help="Only return events newer than N hours (default: use feed-native window).",
    )
    poll.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress per-event console logging (DB still persists).",
    )

    sub.add_parser("list-feeds", help="Print the configured feed list and exit.")
    return p


async def _run_poll(args: argparse.Namespace) -> int:
    level = logging.WARNING if args.quiet else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        force=True,
    )
    service = WatcherService()
    outcome = await service.poll(
        only=args.regulator, since_hours=args.since_hours
    )
    summary = {
        "fetched": outcome.fetched,
        "new_events": outcome.new_events,
        "feeds_polled": outcome.feeds_polled,
        "feeds_errored": outcome.feeds_errored,
        "per_regulator": outcome.per_regulator,
        "duration_seconds": round(outcome.duration_seconds, 2),
    }
    print(json.dumps(summary, indent=2))
    return 0


def _run_list() -> int:
    rows = [
        {"regulator": f.regulator, "url": getattr(f, "url", "<scrape>")}
        for f in default_feeds()
    ]
    print(json.dumps(rows, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.cmd == "poll":
        return asyncio.run(_run_poll(args))
    if args.cmd == "list-feeds":
        return _run_list()
    return 2


if __name__ == "__main__":
    sys.exit(main())
