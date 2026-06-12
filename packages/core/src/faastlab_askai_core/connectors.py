"""Web-connector configuration model + helpers (knowledge ingestion #8).

A *connector* is a tenant-configured web crawl source — a set of start URLs
plus a crawl mode (single page / sitemap / follow-children) and bounds (max
pages, depth, include/exclude filters). The worker runs it and ingests the
fetched pages through the normal pipeline, replacing manual CLI ingest.

Config + a capped run history live in `tenant.settings["connectors"]` (a JSONB
overlay, mirroring how the #6 governance policy is stored) so there's no schema
migration and the feature is decoupled from other in-flight work. If run
history ever needs to scale beyond a handful of connectors, promote it to a
dedicated table.

Everything here is pure (operates on plain dicts/lists) so it unit-tests
without a database; the route layer does the `tenant.settings` read/write.
"""

from __future__ import annotations

from typing import Any

# Defaults / bounds — keep crawls polite and finite.
DEFAULT_MAX_PAGES = 50
MAX_MAX_PAGES = 2000
DEFAULT_MAX_DEPTH = 2
MAX_MAX_DEPTH = 6
# How many run records to retain per connector (newest first).
RUN_HISTORY_LIMIT = 20

VALID_MODES = ("page", "sitemap", "crawl")


def _clean_list(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    return [str(v).strip() for v in values if str(v).strip()]


def normalize_connector(raw: dict[str, Any]) -> dict[str, Any]:
    """Coerce a connector definition into a bounded, well-typed dict.

    Clamps page/depth limits, restricts the mode to a known value, and drops
    empties — so a malformed or hostile config can't produce an unbounded
    crawl. Preserves server-managed fields (`id`, `created_at`, `runs`,
    `last_run_at`) if present.
    """
    mode = str(raw.get("mode") or "crawl").lower()
    if mode not in VALID_MODES:
        mode = "crawl"
    max_pages = _clamp(raw.get("max_pages"), DEFAULT_MAX_PAGES, 1, MAX_MAX_PAGES)
    max_depth = _clamp(raw.get("max_depth"), DEFAULT_MAX_DEPTH, 0, MAX_MAX_DEPTH)
    interval = raw.get("schedule_interval_minutes")
    interval_val = (
        _clamp(interval, 60, 5, 7 * 24 * 60) if interval not in (None, "", 0) else None
    )
    out: dict[str, Any] = {
        "name": str(raw.get("name") or "Untitled connector").strip()[:128],
        "mode": mode,
        "start_urls": _clean_list(raw.get("start_urls"))[:50],
        "url_prefix": (str(raw.get("url_prefix")).strip() or None)
        if raw.get("url_prefix")
        else None,
        "include": _clean_list(raw.get("include"))[:50],
        "exclude": _clean_list(raw.get("exclude"))[:50],
        "max_pages": max_pages,
        "max_depth": max_depth,
        "doc_type": (str(raw.get("doc_type")).strip().lower()[:64] or None)
        if raw.get("doc_type")
        else None,
        "enabled": bool(raw.get("enabled", True)),
        "schedule_interval_minutes": interval_val,
    }
    # Preserve server-managed fields.
    for key in ("id", "created_at", "last_run_at"):
        if raw.get(key) is not None:
            out[key] = raw[key]
    out["runs"] = list(raw.get("runs") or [])
    return out


def _clamp(value: Any, default: int, lo: int, hi: int) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, n))


def list_connectors(settings: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Return the connector definitions from a tenant settings dict."""
    if not settings:
        return []
    block = settings.get("connectors")
    if not isinstance(block, dict):
        return []
    items = block.get("items")
    return list(items) if isinstance(items, list) else []


def find_connector(
    settings: dict[str, Any] | None, connector_id: str
) -> dict[str, Any] | None:
    for c in list_connectors(settings):
        if c.get("id") == connector_id:
            return c
    return None


def upsert_connector(
    items: list[dict[str, Any]], connector: dict[str, Any]
) -> list[dict[str, Any]]:
    """Insert or replace `connector` (matched by `id`) in `items`. Pure."""
    cid = connector.get("id")
    replaced = False
    out: list[dict[str, Any]] = []
    for c in items:
        if c.get("id") == cid:
            out.append(connector)
            replaced = True
        else:
            out.append(c)
    if not replaced:
        out.append(connector)
    return out


def remove_connector(
    items: list[dict[str, Any]], connector_id: str
) -> list[dict[str, Any]]:
    return [c for c in items if c.get("id") != connector_id]


def append_run(connector: dict[str, Any], run: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of `connector` with `run` prepended to its history
    (capped) and `last_run_at` advanced. Pure."""
    runs = [run, *list(connector.get("runs") or [])][:RUN_HISTORY_LIMIT]
    return {
        **connector,
        "runs": runs,
        "last_run_at": run.get("finished_at") or run.get("started_at"),
    }


def is_due(connector: dict[str, Any], now_epoch: float) -> bool:
    """True if an enabled, scheduled connector is due to run again.

    `now_epoch` and the stored `last_run_epoch` are plain seconds so the
    decision is deterministic and testable. A connector with no schedule or
    that's disabled is never due.
    """
    if not connector.get("enabled", True):
        return False
    interval = connector.get("schedule_interval_minutes")
    if not interval:
        return False
    last = connector.get("last_run_epoch")
    if last is None:
        return True  # never run → due now
    return (now_epoch - float(last)) >= float(interval) * 60.0
