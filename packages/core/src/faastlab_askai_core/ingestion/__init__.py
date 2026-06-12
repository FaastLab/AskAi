"""Ingestion pipeline — the Azure-shaped declarative backbone.

See docs/ingestion-pipeline-design.md. Phase 1 ships the data model (ORM in
db/models.py + migration 0009) and these pure default definitions; the runner,
skillset engine, presets, and dashboard land in later phases.
"""

from faastlab_askai_core.ingestion.defaults import (
    REGULATOR_CATEGORIES,
    SKILL_TYPES,
    SOURCE_KINDS,
    default_index_fields,
    default_skillset_skills,
)

__all__ = [
    "REGULATOR_CATEGORIES",
    "SKILL_TYPES",
    "SOURCE_KINDS",
    "default_index_fields",
    "default_skillset_skills",
]
