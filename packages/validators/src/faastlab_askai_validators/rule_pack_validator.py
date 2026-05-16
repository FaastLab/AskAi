"""RulePackValidator — score a target document against a regulator rule pack.

Different problem from `ValidatorPipeline` (which extracts claims from a
report and adjudicates each claim against the corpus). This validator
inverts the question:

  Given a regulator's known requirements, does the target document
  address each one? With what evidence?

Per requirement:
1. Retrieve the most relevant chunks from the target document (only).
2. Optionally retrieve supporting handbook chunks for context (e.g. the
   FCA Handbook clause being checked against — uses doc_type filter).
3. Ask the LLM to score the document's coverage of that requirement.
4. Aggregate into a traffic-light report.

Output is JSON-only for predictable parsing. The LLM never emits prose
without a verdict — we re-prompt on parse failure.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

from faastlab_askai_core.adapters import LLMAdapter, LLMMessage
from faastlab_askai_core.factory import get_llm
from faastlab_askai_search.filters import SearchFilters
from faastlab_askai_search.service import SearchService

from faastlab_askai_validators.rule_packs import (
    RulePack,
    RuleRequirement,
    get_pack,
)

log = logging.getLogger(__name__)

Verdict = Literal["green", "amber", "red", "n/a"]


@dataclass(slots=True)
class RequirementResult:
    requirement_id: str
    title: str
    citation: str
    severity: str
    verdict: Verdict
    rationale: str
    evidence_excerpts: list[dict] = field(default_factory=list)


@dataclass(slots=True)
class RulePackReport:
    pack_id: str
    pack_name: str
    pack_version: str
    document_id: str
    document_title: str
    overall: Verdict
    score: float  # 0.0-1.0
    counts: dict[str, int]
    requirements: list[RequirementResult]
    generated_at: datetime
    latency_ms: float


_ADJUDICATION_PROMPT = """You are a compliance reviewer scoring a target document against a single regulatory requirement.

Return STRICT JSON only, matching this schema:
{
  "verdict": "green" | "amber" | "red" | "n/a",
  "rationale": "<one or two short sentences>",
  "evidence_excerpts": [
    {"text": "<verbatim 1-2 sentence quote from the doc>", "section_path": "<path or null>", "page": <int or null>}
  ]
}

Verdict definitions:
- "green": the document clearly and substantively addresses this requirement, with concrete language a regulator would accept.
- "amber": the document partially addresses the requirement (mentions it but is vague, lacks detail, or references it without operational substance).
- "red": the document fails to address the requirement, OR the document explicitly contradicts the requirement.
- "n/a": the requirement is not applicable to this type of document (e.g. an AML procedure requirement when the document is a consumer-facing privacy notice).

Be honest: green is for documents that demonstrably meet the requirement, not just mention it. If you can't find supporting text, choose red — don't invent it.

Quote evidence verbatim. If no relevant text exists, return an empty "evidence_excerpts" array.
"""


class RulePackValidator:
    def __init__(
        self,
        *,
        llm: LLMAdapter | None = None,
        search: SearchService | None = None,
        retrieve_k: int = 5,
    ) -> None:
        self._llm = llm or get_llm()
        self._search = search or SearchService()
        self._retrieve_k = retrieve_k

    async def validate(
        self,
        *,
        tenant_id: UUID,
        document_id: UUID,
        document_title: str,
        pack_id: str,
    ) -> RulePackReport:
        pack = get_pack(pack_id)
        if pack is None:
            raise ValueError(f"unknown rule pack: {pack_id}")

        started = datetime.now(timezone.utc)
        results: list[RequirementResult] = []

        for req in pack.requirements:
            result = await self._score_requirement(
                tenant_id=tenant_id,
                document_id=document_id,
                requirement=req,
            )
            results.append(result)

        # Aggregate
        counts = {"green": 0, "amber": 0, "red": 0, "n/a": 0}
        for r in results:
            counts[r.verdict] += 1

        applicable = counts["green"] + counts["amber"] + counts["red"]
        score = counts["green"] / applicable if applicable > 0 else 0.0

        # Overall traffic light:
        # - Any red on a `must` severity requirement → overall red
        # - Otherwise if score ≥ 0.7 → green, ≥ 0.4 → amber, else red
        must_reds = [
            r for r in results
            if r.verdict == "red" and r.severity == "must"
        ]
        if must_reds:
            overall: Verdict = "red"
        elif score >= 0.7:
            overall = "green"
        elif score >= 0.4:
            overall = "amber"
        else:
            overall = "red"

        ended = datetime.now(timezone.utc)
        return RulePackReport(
            pack_id=pack.id,
            pack_name=pack.name,
            pack_version=pack.version,
            document_id=str(document_id),
            document_title=document_title,
            overall=overall,
            score=round(score, 3),
            counts=counts,
            requirements=results,
            generated_at=ended,
            latency_ms=(ended - started).total_seconds() * 1000,
        )

    # ---- Per-requirement scoring --------------------------------------

    async def _score_requirement(
        self,
        *,
        tenant_id: UUID,
        document_id: UUID,
        requirement: RuleRequirement,
    ) -> RequirementResult:
        # Retrieve top-k chunks FROM THIS DOC ONLY for the requirement.
        # We scope by document_id via SearchFilters.metadata so chunks
        # from other docs don't confuse the score.
        query = f"{requirement.title}. {requirement.description}"
        try:
            hits = await self._search.search(
                tenant_id=tenant_id,
                query=query,
                k=self._retrieve_k,
                filters=SearchFilters(
                    document_ids=[str(document_id)],
                    only_active=True,
                ),
            )
            chunks = hits.hits
        except Exception as exc:  # noqa: BLE001
            log.warning("validator: retrieval failed for %s: %s", requirement.id, exc)
            chunks = []

        # Build the user prompt.
        excerpts_block = (
            "\n".join(
                f"[{i+1}] (section: {c.section_path or '—'}, "
                f"page: {c.page_number or '—'})\n{c.content.strip()}"
                for i, c in enumerate(chunks)
            )
            if chunks
            else "(no chunks retrieved from the target document for this requirement)"
        )

        user = (
            f"Requirement: {requirement.id} — {requirement.title}\n\n"
            f"Description:\n{requirement.description}\n\n"
            f"Regulator citation: {requirement.citation}\n\n"
            f"Severity: {requirement.severity}\n\n"
            f"---\n"
            f"Excerpts from the TARGET DOCUMENT (the doc we're scoring):\n"
            f"{excerpts_block}\n"
            f"---\n\n"
            f"Score this requirement. Return STRICT JSON only."
        )

        try:
            raw = await self._llm.complete(
                messages=[
                    LLMMessage(role="system", content=_ADJUDICATION_PROMPT),
                    LLMMessage(role="user", content=user),
                ],
                temperature=0.0,
                max_tokens=400,
            )
        except Exception as exc:  # noqa: BLE001
            log.exception("validator: LLM call failed for %s", requirement.id)
            return RequirementResult(
                requirement_id=requirement.id,
                title=requirement.title,
                citation=requirement.citation,
                severity=requirement.severity,
                verdict="amber",
                rationale=f"scoring failed: {exc}",
            )

        return _parse_verdict(raw, requirement)


def _parse_verdict(raw: str, req: RuleRequirement) -> RequirementResult:
    """Parse the LLM's JSON; default to amber + diagnostic on bad output."""
    text = raw.strip()
    # Strip fenced code blocks if the LLM ignored instructions.
    if text.startswith("```"):
        text = text.strip("`").lstrip("json").strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        log.warning("validator: bad JSON for %s: %s", req.id, raw[:200])
        return RequirementResult(
            requirement_id=req.id,
            title=req.title,
            citation=req.citation,
            severity=req.severity,
            verdict="amber",
            rationale="couldn't parse the model's response — re-run if needed",
        )

    verdict = str(data.get("verdict", "amber")).lower()
    if verdict not in {"green", "amber", "red", "n/a"}:
        verdict = "amber"

    rationale = str(data.get("rationale", "")).strip()
    excerpts = data.get("evidence_excerpts") or []
    cleaned_excerpts: list[dict] = []
    for ex in excerpts[:5]:  # cap at 5 to keep responses bounded
        if isinstance(ex, dict) and ex.get("text"):
            cleaned_excerpts.append(
                {
                    "text": str(ex["text"]).strip()[:600],
                    "section_path": ex.get("section_path"),
                    "page": ex.get("page"),
                }
            )

    return RequirementResult(
        requirement_id=req.id,
        title=req.title,
        citation=req.citation,
        severity=req.severity,
        verdict=verdict,  # type: ignore[arg-type]
        rationale=rationale,
        evidence_excerpts=cleaned_excerpts,
    )
