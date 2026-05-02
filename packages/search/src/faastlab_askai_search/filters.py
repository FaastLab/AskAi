"""Search-time filter dataclass.

Filters are tenant-scoped (the SearchService injects `tenant_id`) plus
common metadata facets like `doc_type` and `is_active`. Custom JSONB
metadata filters travel as a free-form dict.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(slots=True)
class SearchFilters:
    """User-supplied filters; tenant_id is injected separately."""

    doc_types: list[str] | None = None
    effective_after: datetime | None = None
    effective_before: datetime | None = None
    only_active: bool = True            # exclude superseded by default
    metadata: dict[str, str] = field(default_factory=dict)
    document_ids: list[str] | None = None  # restrict to these doc UUIDs
