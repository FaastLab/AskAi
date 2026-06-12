"""Canonical default definitions for the ingestion pipeline.

Pure data + builders (no DB, no I/O) so they unit-test trivially and can seed
the default Skillset and IndexProfile rows in a later phase. These encode
*today's* hardcoded `IngestionPipeline` behaviour as an explicit, editable
skillset — so when phase 2 makes the pipeline skill-driven, the default
reproduces current behaviour exactly and nothing regresses.
"""

from __future__ import annotations

from typing import Any

# ---- Vocabularies -----------------------------------------------------------

# Connector kinds a Source can use. `rss` folds the regulator watcher in
# (design §7, phase 3); `govuk_api` is the gov.uk Content API used for HMRC
# manuals' child sections.
SOURCE_KINDS: tuple[str, ...] = (
    "web",
    "sitemap",
    "filesystem",
    "s3",
    "govuk_api",
    "rss",
)

# Regulator categories shipped as presets (design §7, phase 6). FOS = Financial
# Ombudsman Service.
REGULATOR_CATEGORIES: tuple[str, ...] = (
    "fca",
    "pra",
    "boe",
    "hmrc",
    "ico",
    "tpr",
    "fos",
    "custom",
)

# Skill types in execution order. Each Skillset is an ordered subset of these.
SKILL_TYPES: tuple[str, ...] = (
    "parse",
    "clean",
    "chunk",
    "extract_metadata",
    "summarise",
    "keyphrases",
    "embed",
)


# ---- Default skillset -------------------------------------------------------


def default_skillset_skills() -> list[dict[str, Any]]:
    """The ordered skills reproducing today's `IngestionPipeline` behaviour.

    `summarise` / `keyphrases` are LLM-backed (cost tokens via the gateway) and
    so ship **disabled** by default — enrichment is opt-in. `parse → clean →
    chunk → extract_metadata → embed` is the always-on text path.
    """
    return [
        {"type": "parse", "config": {}},
        {"type": "clean", "config": {"strip_nulls": True, "detect_soft_404": True}},
        {"type": "chunk", "config": {"max_tokens": 800, "overlap": 120}},
        {"type": "extract_metadata", "config": {"from_url": True}},
        {"type": "summarise", "config": {}, "enabled": False},
        {"type": "keyphrases", "config": {}, "enabled": False},
        {"type": "embed", "config": {}},
    ]


# ---- Default index profile --------------------------------------------------


def _field(
    name: str,
    *,
    type: str = "string",
    searchable: bool = False,
    filterable: bool = False,
    facetable: bool = False,
    retrievable: bool = True,
    source: str = "document",
) -> dict[str, Any]:
    """One field definition for an IndexProfile (design §5). `source` is where
    the value comes from (a document attribute or a skill output)."""
    return {
        "name": name,
        "type": type,
        "source": source,
        "searchable": searchable,
        "filterable": filterable,
        "facetable": facetable,
        "retrievable": retrievable,
    }


def default_index_fields() -> list[dict[str, Any]]:
    """The baseline field profile — maps onto existing Document/Chunk columns +
    metadata, with the flags the search/filter/citation layers already honour.
    Extra metadata fields (e.g. instrument_type) are added later by editing the
    profile, no migration needed."""
    return [
        _field("title", searchable=True),
        _field("content", type="text", searchable=True, source="chunk"),
        _field("regulator", filterable=True, facetable=True, source="extract_metadata"),
        _field("doc_type", filterable=True, facetable=True),
        _field("effective_date", type="date", filterable=True),
        _field("section_path", source="chunk"),
        _field("source_uri"),
        # Provenance / licensing (design §10) — populated for curated presets.
        _field("license", filterable=True, facetable=True),
        _field("source_authority", filterable=True, source="extract_metadata"),
        _field("attribution"),
    ]
