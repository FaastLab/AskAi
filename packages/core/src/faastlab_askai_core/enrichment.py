"""Per-tenant document-enrichment preference (summaries + keyphrases).

A customer-facing toggle: "auto-generate summaries & keyphrases for my
documents". Stored in `tenant.settings["enrichment"]["auto"]` (JSONB overlay —
no migration), and read in three places:
  - the ingest pipeline (auto-enqueue enrichment when a doc lands),
  - the periodic sweep (self-heal docs that still have no summary),
  - the API (read/write the toggle + report status).

When the tenant hasn't chosen, it falls back to the deployment default
(`SUMMARISE_ON_INGEST`). Pure functions (operate on plain dicts) so they unit
test without a database.
"""

from __future__ import annotations

from typing import Any


def enrichment_enabled(tenant_settings: dict[str, Any] | None, *, default: bool) -> bool:
    """Whether auto summary+keyphrases is on for this tenant.

    Returns the tenant's explicit choice if set, else the deployment `default`.
    """
    block = (tenant_settings or {}).get("enrichment")
    if not isinstance(block, dict):
        return default
    value = block.get("auto")
    return bool(value) if isinstance(value, bool) else default


def with_enrichment(
    tenant_settings: dict[str, Any] | None, *, auto: bool
) -> dict[str, Any]:
    """Return a copy of the settings dict with the enrichment toggle set."""
    settings = dict(tenant_settings or {})
    block = dict(settings.get("enrichment") or {})
    block["auto"] = bool(auto)
    settings["enrichment"] = block
    return settings
