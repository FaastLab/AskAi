"""Ingestion pipeline — the Azure-shaped declarative backbone.

See docs/ingestion-pipeline-design.md. The data model (ORM in db/models.py +
migration 0009), the default skill/field definitions, and the regulator presets
shipped ready to toggle on.
"""

from faastlab_askai_core.ingestion.defaults import (
    REGULATOR_CATEGORIES,
    SKILL_TYPES,
    SOURCE_KINDS,
    default_index_fields,
    default_skillset_skills,
)
from faastlab_askai_core.ingestion.presets import find_preset, regulator_presets
from faastlab_askai_core.ingestion.scheduler import (
    folder_prefix,
    is_indexer_due,
    schedule_interval_minutes,
    storage_key_for,
)

__all__ = [
    "REGULATOR_CATEGORIES",
    "SKILL_TYPES",
    "SOURCE_KINDS",
    "default_index_fields",
    "default_skillset_skills",
    "find_preset",
    "folder_prefix",
    "is_indexer_due",
    "regulator_presets",
    "schedule_interval_minutes",
    "storage_key_for",
]
