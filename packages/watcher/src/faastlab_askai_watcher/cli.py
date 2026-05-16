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
    poll.add_argument(
        "--json",
        action="store_true",
        help="Emit the poll outcome as JSON (for scripting). Default: text table.",
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
    if args.json:
        summary = {
            "polled_at": outcome.polled_at.isoformat(),
            "fetched": outcome.fetched,
            "new_events": outcome.new_events,
            "feeds_polled": outcome.feeds_polled,
            "feeds_errored": outcome.feeds_errored,
            "per_regulator": outcome.per_regulator,
            "duration_seconds": round(outcome.duration_seconds, 2),
            "feeds": [
                {
                    "regulator": f.regulator,
                    "ok": f.ok,
                    "fetched": f.fetched,
                    "new": f.new,
                    "error": f.error,
                }
                for f in outcome.feeds
            ],
        }
        print(json.dumps(summary, indent=2))
    else:
        print(_render_text_report(outcome))
    return 0


def _render_text_report(outcome) -> str:
    """Compact one-screen poll summary for terminal use."""
    duration = f"{outcome.duration_seconds:.1f}s"
    ok_count = sum(1 for f in outcome.feeds if f.ok)
    err_count = sum(1 for f in outcome.feeds if not f.ok)
    when = outcome.polled_at.strftime("%Y-%m-%d %H:%M:%S UTC")

    lines: list[str] = [
        "",
        f"╭─ Watcher poll — {when} ─" + "─" * max(0, 38 - len(when)),
        f"│ Feeds polled:  {outcome.feeds_polled:>4d}   "
        f"│ ok: {ok_count}   failed: {err_count}",
        f"│ Total fetched: {outcome.fetched:>4d}   "
        f"│ new events: {outcome.new_events}",
        f"│ Duration:     {duration:>5s}",
        "├" + "─" * 60,
        f"│ {'regulator':<10s}  {'status':<7s}  {'fetched':>7s}  {'new':>4s}  detail",
        "├" + "─" * 60,
    ]
    for f in outcome.feeds:
        if f.ok:
            status = "✅ OK"
            detail = ""
            if f.new == 0 and f.fetched > 0:
                detail = "all duplicates (already in DB)"
        else:
            status = "❌ FAIL"
            detail = f.error or "unknown error"
        lines.append(
            f"│ {f.regulator:<10s}  {status:<7s}  {f.fetched:>7d}  {f.new:>4d}  {detail}"
        )
    lines.append("╰" + "─" * 60)
    return "\n".join(lines) + "\n"


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
