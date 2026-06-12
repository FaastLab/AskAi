"""Phase-1 ingestion pipeline: default definitions + ORM table registration.

Pure — no DB connection. Verifies the canonical defaults are well-formed and
that the five tables are registered on the SQLAlchemy metadata (so the
migration and models stay in sync).
"""

from __future__ import annotations

from faastlab_askai_core.db import Base, Indexer, IndexerRun, IndexProfile, Skillset, Source
from faastlab_askai_core.ingestion import (
    REGULATOR_CATEGORIES,
    SKILL_TYPES,
    SOURCE_KINDS,
    default_index_fields,
    default_skillset_skills,
)

# ---- vocabularies ----------------------------------------------------------


def test_vocabularies_cover_design() -> None:
    assert "web" in SOURCE_KINDS and "rss" in SOURCE_KINDS  # watcher convergence
    assert "govuk_api" in SOURCE_KINDS  # HMRC manuals
    assert {"fca", "pra", "boe", "hmrc", "ico", "fos"} <= set(REGULATOR_CATEGORIES)


# ---- default skillset ------------------------------------------------------


def test_default_skillset_is_ordered_known_skills() -> None:
    skills = default_skillset_skills()
    types = [s["type"] for s in skills]
    # Every skill type is known, and the always-on text path is in order.
    assert all(t in SKILL_TYPES for t in types)
    assert types.index("parse") < types.index("chunk") < types.index("embed")


def test_llm_enrichment_skills_default_off() -> None:
    by_type = {s["type"]: s for s in default_skillset_skills()}
    assert by_type["summarise"].get("enabled") is False
    assert by_type["keyphrases"].get("enabled") is False
    # The text path skills have no explicit disable.
    assert by_type["parse"].get("enabled", True) is True


# ---- default index profile -------------------------------------------------


def test_default_index_fields_have_required_flags() -> None:
    fields = default_index_fields()
    names = {f["name"] for f in fields}
    assert {"title", "content", "regulator", "license"} <= names
    # Every field declares the full flag set.
    for f in fields:
        for flag in ("searchable", "filterable", "facetable", "retrievable"):
            assert isinstance(f[flag], bool)


def test_content_searchable_and_license_filterable() -> None:
    fields = {f["name"]: f for f in default_index_fields()}
    assert fields["content"]["searchable"] is True
    assert fields["license"]["filterable"] is True  # provenance is filterable


# ---- ORM table registration ------------------------------------------------


def test_ingestion_tables_registered() -> None:
    tables = set(Base.metadata.tables)
    assert {
        "ingestion_sources",
        "ingestion_skillsets",
        "ingestion_index_profiles",
        "ingestion_indexers",
        "ingestion_indexer_runs",
    } <= tables


def test_models_have_expected_tablenames() -> None:
    assert Source.__tablename__ == "ingestion_sources"
    assert Skillset.__tablename__ == "ingestion_skillsets"
    assert IndexProfile.__tablename__ == "ingestion_index_profiles"
    assert Indexer.__tablename__ == "ingestion_indexers"
    assert IndexerRun.__tablename__ == "ingestion_indexer_runs"


def test_preset_tenant_nullable_runner_not() -> None:
    # System presets allow tenant_id IS NULL; an indexer/run is always scoped.
    assert Source.__table__.c.tenant_id.nullable is True
    assert Skillset.__table__.c.tenant_id.nullable is True
    assert IndexProfile.__table__.c.tenant_id.nullable is True
    assert Indexer.__table__.c.tenant_id.nullable is False
    assert IndexerRun.__table__.c.tenant_id.nullable is False
