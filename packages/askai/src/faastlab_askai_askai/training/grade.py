"""Rubric grading for training submissions (#7 Compliance Training).

Ported from Academy's ``rubric.py``. The LLM grades a submission
criterion-by-criterion and returns strict JSON; we **clamp** each awarded score
to ``[0, max_points]`` and compute a weighted total, so a misbehaving model can
never inflate a score past the rubric's ceiling — the grade is defensible.

Completion flows through the ``AIGateway`` with ``purpose="grading"`` so grading
is governed and metered like every other sovereign call. The criterion JSONB
shape is tolerant (bare list, ``{"items": [...]}``, or a single object) because
rubrics are authored by humans and arrive in several shapes.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from faastlab_askai_core.adapters import LLMMessage
from faastlab_askai_core.gateway import AIGateway, GatewayContext

log = logging.getLogger(__name__)

_SYSTEM = (
    "You are a rigorous, fair compliance assessor. You grade a learner's answer "
    "against a rubric, one criterion at a time. You never invent facts about the "
    "submission. You output ONLY valid JSON, no prose, no code fences."
)


@dataclass(slots=True)
class GradeResult:
    """A graded submission. ``status`` distinguishes complete / needs_rubric /
    error so the caller can react without parsing ``feedback``."""

    scores: list[dict[str, Any]]
    total_score: float | None
    max_score: float | None
    feedback: str
    status: str = "complete"
    passed: bool | None = None


def normalise_criteria(criteria: Any) -> list[dict[str, Any]]:
    """Accept the several shapes a rubric's ``criteria`` JSONB may take.

    Supports a bare list, ``{"items": [...]}``, or ``{}`` → ``[]``. Each item is
    coerced to ``{key, description, max_points, weight}`` with sane defaults.
    """
    if isinstance(criteria, dict):
        items = criteria.get("items", [])
    elif isinstance(criteria, list):
        items = criteria
    else:
        items = []

    out: list[dict[str, Any]] = []
    for i, raw in enumerate(items):
        if not isinstance(raw, dict):
            continue
        out.append(
            {
                "key": str(raw.get("key") or raw.get("name") or f"criterion_{i + 1}"),
                "description": str(raw.get("description") or raw.get("desc") or ""),
                "max_points": float(raw.get("max_points") or raw.get("points") or 10),
                "weight": float(raw.get("weight") or 1.0),
            }
        )
    return out


class TrainingGrader:
    """Governed rubric grader. Stateless; construct once and share."""

    def __init__(self, *, gateway: AIGateway | None = None) -> None:
        self._gateway = gateway or AIGateway()

    async def grade(
        self,
        *,
        tenant_id: UUID,
        content: str | None,
        criteria: Any,
        instructions: str | None = None,
        context: str | None = None,
        pass_mark_pct: float | None = 70.0,
        user_id: str | None = None,
        request_id: str | None = None,
    ) -> GradeResult:
        """Score ``content`` against ``criteria`` using the sovereign LLM.

        ``context`` is optional grounding (e.g. corpus excerpts) appended to the
        prompt. ``pass_mark_pct`` decides ``passed`` for the training record;
        ``None`` leaves ``passed`` unset. Returns a fully-populated, clamped
        result — a malformed model reply degrades to ``status="error"`` rather
        than raising.
        """
        crit = normalise_criteria(criteria)
        if not crit:
            return GradeResult(
                scores=[],
                total_score=None,
                max_score=None,
                feedback="No rubric criteria defined — cannot score automatically.",
                status="needs_rubric",
            )

        prompt = _build_prompt(content=content or "", instructions=instructions, criteria=crit)
        if context:
            prompt += f"\n\nREFERENCE MATERIAL (for grounding / originality):\n{context}"

        ctx = GatewayContext(
            tenant_id=tenant_id,
            user_id=user_id,
            purpose="grading",
            request_id=request_id,
        )
        try:
            result = await self._gateway.complete(
                ctx,
                [
                    LLMMessage(role="system", content=_SYSTEM),
                    LLMMessage(role="user", content=prompt),
                ],
                temperature=0.0,
                max_tokens=1800,
            )
            parsed = _parse_json(result.text)
        except (ValueError, KeyError, json.JSONDecodeError) as exc:
            return GradeResult(
                scores=[],
                total_score=None,
                max_score=sum(c["max_points"] for c in crit) or None,
                feedback=f"Automated grading failed to parse a result: {exc}",
                status="error",
            )

        rows = parsed if isinstance(parsed, list) else parsed.get("scores", [])
        by_key = {str(r.get("key")): r for r in rows if isinstance(r, dict)}

        scores: list[dict[str, Any]] = []
        weighted_total = 0.0
        weighted_max = 0.0
        for c in crit:
            row = by_key.get(c["key"], {})
            raw_points = row.get("points")
            max_points = c["max_points"]
            # Clamp to [0, max] so the model can never inflate past the ceiling.
            points = (
                0.0 if raw_points is None else max(0.0, min(float(raw_points), max_points))
            )
            weight = c["weight"]
            weighted_total += points * weight
            weighted_max += max_points * weight
            scores.append(
                {
                    "key": c["key"],
                    "points": points,
                    "max_points": max_points,
                    "weight": weight,
                    "comment": str(row.get("comment") or ""),
                }
            )

        pct = (weighted_total / weighted_max * 100) if weighted_max else None
        passed = None if (pct is None or pass_mark_pct is None) else pct >= pass_mark_pct
        return GradeResult(
            scores=scores,
            total_score=round(weighted_total, 2),
            max_score=round(weighted_max, 2),
            feedback=_summarise_feedback(scores, pct),
            status="complete",
            passed=passed,
        )


def _build_prompt(
    *, content: str, instructions: str | None, criteria: list[dict[str, Any]]
) -> str:
    lines = [
        "Grade the SUBMISSION against each rubric CRITERION.",
        "",
        "Return a JSON array. For every criterion return an object:",
        '{"key": <criterion key>, "points": <number 0..max_points>, '
        '"comment": <one or two sentences citing the submission>}',
        "",
        "RUBRIC CRITERIA:",
    ]
    for c in criteria:
        lines.append(
            f"- key={c['key']} (max_points={c['max_points']}): {c['description']}"
        )
    if instructions:
        lines += ["", "ASSESSMENT INSTRUCTIONS:", instructions]
    lines += ["", "SUBMISSION:", content or "(empty submission)"]
    return "\n".join(lines)


def _summarise_feedback(scores: list[dict[str, Any]], pct: float | None) -> str:
    if pct is None:
        return "Scored, but no maximum was defined for the rubric."
    strongest = max(
        scores, key=lambda s: s["points"] / (s["max_points"] or 1), default=None
    )
    weakest = min(
        scores, key=lambda s: s["points"] / (s["max_points"] or 1), default=None
    )
    parts = [f"Overall: {pct:.0f}%."]
    if strongest:
        parts.append(f"Strongest: {strongest['key']}.")
    if weakest and weakest is not strongest:
        parts.append(f"Needs work: {weakest['key']}.")
    return " ".join(parts)


def _parse_json(text: str) -> Any:
    """Parse model output as JSON, tolerating a Markdown ```json code fence."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[-1] if "\n" in cleaned else cleaned
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()
    return json.loads(cleaned)
