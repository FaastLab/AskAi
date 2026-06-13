"""Compliance training (#7) — grounded generation + rubric grading.

Generation and grading both run on AskAi's own sovereign seams: retrieval via
``SearchService`` (grounded + cited) and completion via the governed
``AIGateway`` (metered, quota'd, policy-enforced). Ported and adapted from the
Academy ``materials.py`` / ``rubric.py`` engines.
"""

from faastlab_askai_askai.training.generate import (
    GeneratedArtefact,
    TrainingGenerator,
)
from faastlab_askai_askai.training.grade import (
    GradeResult,
    TrainingGrader,
    normalise_criteria,
)

__all__ = [
    "GeneratedArtefact",
    "GradeResult",
    "TrainingGenerator",
    "TrainingGrader",
    "normalise_criteria",
]
