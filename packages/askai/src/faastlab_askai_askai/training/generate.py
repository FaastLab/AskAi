"""Grounded training-material generation (#7 Compliance Training).

Ported from the Academy ``materials.py`` generators, rewired onto AskAi's own
seams so generation is **sovereign and governed by construction**:

* Retrieval goes through ``SearchService`` directly (in-process, GPU-reranked) —
  not an HTTP hop to a second service. Every generated artefact is grounded in,
  and carries citations back to, the tenant's ingested corpus. That traceability
  is the whole point for a compliance regime: a regulator can see *which rule*
  each lesson / question was built from.
* Completion flows through the ``AIGateway`` with ``purpose="training"`` — so it
  inherits per-tenant quota, model-policy enforcement, and exact usage metering.
  Training-generation spend therefore shows up in the Usage dashboard like every
  other call, and never silently leaves the sovereign stack.

The generator family:
  * ``generate_lesson``         — a grounded Markdown lesson (the *delivery* half)
  * ``generate_revision_guide`` — a concise revision guide
  * ``generate_quiz``           — auto-gradable MCQs (answer_index + rationale)
  * ``generate_exam``           — exam Q&A with model answers + marks; can mimic
                                  a past paper via ``example_questions``
  * ``generate_flashcards``     — front/back study cards (optional polish)
  * ``generate_slides``         — a slide-deck outline (optional polish)
  * ``generate_scenario``       — NEW: story → situation → staff conversation →
                                  identify/report → assessment. Built for
                                  behaviour-driven compliance topics (e.g. money
                                  laundering: narrative, red-flag dialogue, the
                                  SAR/MLRO reporting path, and test questions).
  * ``generate_blended``        — a complete module: lesson + quiz, optionally a
                                  scenario, in one grounded pass.

All generators share the same retrieve → ground → cite shape and differ only by
prompt, so adding one is a copy of the prompt plus the same wiring.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from faastlab_askai_core.adapters import LLMMessage
from faastlab_askai_core.gateway import AIGateway, GatewayContext
from faastlab_askai_search.service import SearchService

log = logging.getLogger(__name__)

# How many corpus passages to ground each artefact in. 8 mirrors Academy's
# default — enough context for a lesson/exam without blowing the prompt budget.
_GROUND_K = 8


# ---- System prompts (one per artefact kind) ---------------------------------

_LESSON_SYSTEM = (
    "You are an expert compliance instructional designer. You write clear, "
    "accurate training lessons for staff in a regulated firm, using ONLY the "
    "reference passages provided. You never invent rules beyond the references. "
    "Output Markdown."
)
_REVISION_SYSTEM = (
    "You are a tutor writing a concise revision guide from reference passages "
    "ONLY. Use headings, bullet points, and a 'key terms' list. Output Markdown."
)
_QUIZ_SYSTEM = (
    "You are an assessment author. Using ONLY the reference passages, write "
    "multiple-choice questions that test understanding of the rules. Output ONLY "
    "valid JSON."
)
_EXAM_SYSTEM = (
    "You are an experienced compliance exam author. Using ONLY the reference "
    "passages, write exam-style questions each with a full model answer and a "
    "marks allocation. If past/sample questions are provided, MATCH their style, "
    "depth, phrasing and difficulty. Do not invent facts beyond the references. "
    "Output ONLY valid JSON."
)
_FLASHCARD_SYSTEM = (
    "You write study flashcards from reference passages ONLY. Each card has a "
    "concise front (prompt) and back (answer). Output ONLY valid JSON."
)
_SLIDES_SYSTEM = (
    "You are a presentation author. From reference passages ONLY, produce a "
    "training slide-deck outline. Output ONLY valid JSON."
)
_SCENARIO_SYSTEM = (
    "You are a compliance training author who teaches through realistic "
    "workplace stories. Using ONLY the reference passages, you write a scenario "
    "that puts staff in a believable situation, shows a conversation in which "
    "warning signs appear, then tests whether the learner can identify the issue "
    "and follow the correct reporting procedure described in the references. You "
    "never invent obligations or reporting routes beyond the references. Output "
    "ONLY valid JSON."
)


# ---- Result type ------------------------------------------------------------


@dataclass(slots=True)
class GeneratedArtefact:
    """A generated training artefact and its corpus grounding.

    ``kind`` is the artefact type (lesson/quiz/exam/scenario/…). ``body`` holds
    Markdown for prose artefacts; ``data`` holds the structured payload for JSON
    artefacts (questions, cards, slides, the scenario object). ``grounding``
    always carries the citations the artefact was built from — the audit trail.
    """

    kind: str
    topic: str
    title: str
    body: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    grounding: dict[str, Any] = field(default_factory=dict)


class TrainingGenerator:
    """Grounded generator family. Stateless; construct once and share.

    Mirrors ``AskAiService``'s wiring: a ``SearchService`` for retrieval and an
    ``AIGateway`` for governed completion. Inject fakes in tests.
    """

    def __init__(
        self,
        *,
        search: SearchService | None = None,
        gateway: AIGateway | None = None,
        ground_k: int = _GROUND_K,
    ) -> None:
        self._search = search or SearchService()
        self._gateway = gateway or AIGateway()
        self._ground_k = ground_k

    # ---- Internal helpers ---------------------------------------------------

    async def _retrieve(
        self, tenant_id: UUID, topic: str
    ) -> tuple[str, list[dict[str, Any]]]:
        """Return ``(reference_text, citations)`` for ``topic`` from the corpus.

        Grounding is what makes generated content traceable to source material.
        ``meter=False`` — this retrieval is part of a metered *generation* call,
        so we don't also bill a separate ``purpose="search"`` row for it.
        """
        outcome = await self._search.search(
            tenant_id=tenant_id, query=topic, k=self._ground_k, meter=False
        )
        refs: list[str] = []
        citations: list[dict[str, Any]] = []
        for h in outcome.hits:
            title = h.document_title or "source"
            refs.append(f"[{title}] {h.content}")
            citations.append(
                {
                    "document_id": str(h.document_id),
                    "document_title": h.document_title,
                    "chunk_id": str(h.chunk_id),
                    "page_number": h.page_number,
                }
            )
        return "\n\n".join(refs), citations

    def _ctx(
        self, tenant_id: UUID, user_id: str | None, request_id: str | None
    ) -> GatewayContext:
        # purpose="training" → routed + metered as training spend in the ledger.
        return GatewayContext(
            tenant_id=tenant_id,
            user_id=user_id,
            purpose="training",
            request_id=request_id,
        )

    async def _complete(
        self,
        ctx: GatewayContext,
        system: str,
        user: str,
        *,
        max_tokens: int = 1800,
        temperature: float = 0.2,
    ) -> str:
        """One governed completion → assistant text."""
        result = await self._gateway.complete(
            ctx,
            [
                LLMMessage(role="system", content=system),
                LLMMessage(role="user", content=user),
            ],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return result.text

    async def _complete_json(
        self,
        ctx: GatewayContext,
        system: str,
        user: str,
        *,
        max_tokens: int = 2400,
    ) -> Any:
        """Governed completion whose text we parse as JSON.

        The gateway returns raw text (there's no ``complete_json`` primitive), so
        we strip any Markdown code fence the model wrapped the JSON in and parse.
        Callers handle ``ValueError``/``JSONDecodeError`` and degrade to an empty
        result rather than 500 — a misbehaving model must never crash a request.
        """
        text = await self._complete(
            ctx, system, user, max_tokens=max_tokens, temperature=0.2
        )
        return _parse_json(text)

    # ---- Prose artefacts ----------------------------------------------------

    async def generate_lesson(
        self,
        *,
        tenant_id: UUID,
        topic: str,
        objectives: list[str] | None = None,
        user_id: str | None = None,
        request_id: str | None = None,
    ) -> GeneratedArtefact:
        """Generate a single grounded training lesson on ``topic``."""
        ctx = self._ctx(tenant_id, user_id, request_id)
        references, citations = await self._retrieve(tenant_id, topic)
        obj_text = ""
        if objectives:
            obj_text = "\n\nLEARNING OBJECTIVES:\n" + "\n".join(
                f"- {o}" for o in objectives
            )
        prompt = (
            f"Write a training lesson on: {topic}.{obj_text}\n\n"
            "Structure: a short intro, 2-4 sections with headings, and a brief "
            "summary. Cite sources inline as [document title].\n\n"
            f"REFERENCE PASSAGES:\n{references or '(no material found)'}"
        )
        body = await self._complete(ctx, _LESSON_SYSTEM, prompt, max_tokens=1800)
        return GeneratedArtefact(
            kind="lesson",
            topic=topic,
            title=topic,
            body=body,
            grounding={"citations": citations, "objectives": objectives or []},
        )

    async def generate_revision_guide(
        self,
        *,
        tenant_id: UUID,
        topic: str,
        user_id: str | None = None,
        request_id: str | None = None,
    ) -> GeneratedArtefact:
        """Generate a grounded Markdown revision guide."""
        ctx = self._ctx(tenant_id, user_id, request_id)
        references, citations = await self._retrieve(tenant_id, topic)
        prompt = (
            f"Write a revision guide on: {topic}. Include an overview, key points "
            "as bullets, a 'Key terms' glossary, and 3 self-check questions. Cite "
            f"sources inline as [document title].\n\n"
            f"REFERENCE PASSAGES:\n{references or '(none)'}"
        )
        body = await self._complete(ctx, _REVISION_SYSTEM, prompt, max_tokens=1400)
        return GeneratedArtefact(
            kind="revision_guide",
            topic=topic,
            title=f"{topic} — revision guide",
            body=body,
            grounding={"citations": citations},
        )

    # ---- Structured (JSON) artefacts ---------------------------------------

    async def generate_quiz(
        self,
        *,
        tenant_id: UUID,
        topic: str,
        num_questions: int = 5,
        user_id: str | None = None,
        request_id: str | None = None,
    ) -> GeneratedArtefact:
        """Generate a grounded, auto-gradable multiple-choice quiz."""
        ctx = self._ctx(tenant_id, user_id, request_id)
        references, citations = await self._retrieve(tenant_id, topic)
        prompt = (
            f"Write {num_questions} multiple-choice questions on: {topic}.\n"
            'Return JSON: {"questions": [{"question": str, "options": [str, str, '
            'str, str], "answer_index": int, "rationale": str}]}\n\n'
            f"REFERENCE PASSAGES:\n{references or '(no material found)'}"
        )
        try:
            parsed = await self._complete_json(ctx, _QUIZ_SYSTEM, prompt)
        except (ValueError, json.JSONDecodeError):
            parsed = {"questions": []}
        questions = _questions_of(parsed)
        return GeneratedArtefact(
            kind="quiz",
            topic=topic,
            title=f"{topic} — quiz",
            data={"questions": questions},
            grounding={"citations": citations},
        )

    async def generate_exam(
        self,
        *,
        tenant_id: UUID,
        topic: str,
        num_questions: int = 5,
        style: str = "mixed",
        difficulty: str = "mixed",
        example_questions: str | None = None,
        user_id: str | None = None,
        request_id: str | None = None,
    ) -> GeneratedArtefact:
        """Generate grounded, exam-style Q&A — optionally mimicking past papers."""
        ctx = self._ctx(tenant_id, user_id, request_id)
        references, citations = await self._retrieve(tenant_id, topic)
        examples_block = ""
        if example_questions and example_questions.strip():
            examples_block = (
                "\n\nPAST / SAMPLE EXAM QUESTIONS — match this style, format, "
                f"depth and difficulty:\n{example_questions.strip()[:4000]}"
            )
        diff_block = (
            f" Target difficulty level: {difficulty} (calibrate question demand, "
            "marks and answer depth accordingly)."
            if difficulty and difficulty != "mixed"
            else ""
        )
        prompt = (
            f"Write {num_questions} exam questions ({style}) on: {topic}."
            f"{diff_block}{examples_block}\n"
            'Return JSON: {"questions": [{"question": str, "model_answer": str, '
            '"marks": int, "type": str}]}\n\n'
            f"REFERENCE PASSAGES:\n{references or '(no material found)'}"
        )
        try:
            parsed = await self._complete_json(
                ctx, _EXAM_SYSTEM, prompt, max_tokens=3500
            )
        except (ValueError, json.JSONDecodeError):
            parsed = {"questions": []}
        questions = _questions_of(parsed)
        return GeneratedArtefact(
            kind="exam",
            topic=topic,
            title=f"{topic} — exam",
            data={"questions": questions, "style": style, "difficulty": difficulty},
            grounding={"citations": citations},
        )

    async def generate_flashcards(
        self,
        *,
        tenant_id: UUID,
        topic: str,
        num_cards: int = 10,
        user_id: str | None = None,
        request_id: str | None = None,
    ) -> GeneratedArtefact:
        """Generate grounded flashcards (front/back pairs)."""
        ctx = self._ctx(tenant_id, user_id, request_id)
        references, citations = await self._retrieve(tenant_id, topic)
        prompt = (
            f"Write {num_cards} flashcards on: {topic}.\n"
            'Return JSON: {"cards": [{"front": str, "back": str}]}\n\n'
            f"REFERENCE PASSAGES:\n{references or '(no material found)'}"
        )
        try:
            parsed = await self._complete_json(ctx, _FLASHCARD_SYSTEM, prompt)
        except (ValueError, json.JSONDecodeError):
            parsed = {"cards": []}
        cards = parsed.get("cards", []) if isinstance(parsed, dict) else parsed
        return GeneratedArtefact(
            kind="flashcards",
            topic=topic,
            title=f"{topic} — flashcards",
            data={"cards": cards},
            grounding={"citations": citations},
        )

    async def generate_slides(
        self,
        *,
        tenant_id: UUID,
        topic: str,
        num_slides: int = 8,
        user_id: str | None = None,
        request_id: str | None = None,
    ) -> GeneratedArtefact:
        """Generate a grounded slide-deck outline (title + bullets per slide)."""
        ctx = self._ctx(tenant_id, user_id, request_id)
        references, citations = await self._retrieve(tenant_id, topic)
        prompt = (
            f"Create a {num_slides}-slide training deck outline on: {topic}.\n"
            'Return JSON: {"slides": [{"title": str, "bullets": [str, ...], '
            '"notes": str}]}\n\n'
            f"REFERENCE PASSAGES:\n{references or '(no material found)'}"
        )
        try:
            parsed = await self._complete_json(ctx, _SLIDES_SYSTEM, prompt)
        except (ValueError, json.JSONDecodeError):
            parsed = {"slides": []}
        slides = parsed.get("slides", []) if isinstance(parsed, dict) else parsed
        return GeneratedArtefact(
            kind="slides",
            topic=topic,
            title=f"{topic} — slides",
            data={"slides": slides},
            grounding={"citations": citations},
        )

    # ---- Scenario / story-based training (NEW) ------------------------------

    async def generate_scenario(
        self,
        *,
        tenant_id: UUID,
        topic: str,
        role: str | None = None,
        num_questions: int = 4,
        user_id: str | None = None,
        request_id: str | None = None,
    ) -> GeneratedArtefact:
        """Generate a grounded story-based training scenario.

        Produces a narrative, a workplace situation, a staff conversation in
        which warning signs surface (each line flagged if it's a red flag),
        decision points, the correct identify-and-report procedure (e.g. raising
        a SAR to the MLRO for money laundering), and assessment questions — all
        grounded in, and cited back to, the firm's ingested rules. This is the
        behaviour-driven format compliance training actually needs: it tests
        whether staff would *recognise and act*, not just recall a definition.
        """
        ctx = self._ctx(tenant_id, user_id, request_id)
        references, citations = await self._retrieve(tenant_id, topic)
        role_block = (
            f" Write it for the perspective of a {role}." if role else ""
        )
        prompt = (
            f"Create a realistic workplace training scenario on: {topic}."
            f"{role_block}\n"
            "It must teach staff to recognise the warning signs and follow the "
            "exact reporting procedure described in the references.\n"
            "Return JSON with this shape:\n"
            "{\n"
            '  "title": str,\n'
            '  "narrative": str,            // a short story setting the scene\n'
            '  "situation": str,            // the specific situation the staff member faces\n'
            '  "conversation": [{"speaker": str, "line": str, "red_flag": bool, '
            '"note": str}],   // a dialogue; mark which lines are warning signs and why\n'
            '  "red_flags": [str],          // the warning signs a learner should spot\n'
            '  "reporting_steps": [str],    // the correct identify-and-report procedure, '
            "from the references (e.g. who to escalate to, what to file)\n"
            f'  "questions": [{{"question": str, "model_answer": str, "marks": int}}]   '
            f"// {num_questions} assessment questions on spotting and reporting\n"
            "}\n\n"
            "Ground everything in the references — do not invent obligations or "
            "reporting routes beyond them. Cite document titles in reporting_steps "
            "where relevant.\n\n"
            f"REFERENCE PASSAGES:\n{references or '(no material found)'}"
        )
        try:
            parsed = await self._complete_json(
                ctx, _SCENARIO_SYSTEM, prompt, max_tokens=3500
            )
        except (ValueError, json.JSONDecodeError):
            parsed = {}
        if not isinstance(parsed, dict):
            parsed = {}
        title = str(parsed.get("title") or f"{topic} — scenario")
        return GeneratedArtefact(
            kind="scenario",
            topic=topic,
            title=title,
            data={
                "narrative": parsed.get("narrative", ""),
                "situation": parsed.get("situation", ""),
                "conversation": parsed.get("conversation", []),
                "red_flags": parsed.get("red_flags", []),
                "reporting_steps": parsed.get("reporting_steps", []),
                "questions": _questions_of(parsed),
            },
            grounding={"citations": citations},
        )

    # ---- Blended module -----------------------------------------------------

    async def generate_blended(
        self,
        *,
        tenant_id: UUID,
        topic: str,
        objectives: list[str] | None = None,
        num_questions: int = 5,
        include_scenario: bool = True,
        user_id: str | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        """Generate a complete training module in one grounded pass.

        Returns a lesson (the delivery), a quiz (the test), and — for
        behaviour-driven topics — a scenario. This is the "deliver training →
        test → record" loop a compliance regime expects, all tied to the same
        ingested rules so the resulting training record is a coherent audit
        artefact.
        """
        lesson = await self.generate_lesson(
            tenant_id=tenant_id,
            topic=topic,
            objectives=objectives,
            user_id=user_id,
            request_id=request_id,
        )
        quiz = await self.generate_quiz(
            tenant_id=tenant_id,
            topic=topic,
            num_questions=num_questions,
            user_id=user_id,
            request_id=request_id,
        )
        module: dict[str, Any] = {
            "topic": topic,
            "lesson": _artefact_dict(lesson),
            "quiz": _artefact_dict(quiz),
        }
        if include_scenario:
            scenario = await self.generate_scenario(
                tenant_id=tenant_id,
                topic=topic,
                user_id=user_id,
                request_id=request_id,
            )
            module["scenario"] = _artefact_dict(scenario)
        return module


# ---- Module-level helpers ---------------------------------------------------


def _parse_json(text: str) -> Any:
    """Parse model output as JSON, tolerating a Markdown ```json code fence."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        # Drop the opening fence (``` or ```json) and the trailing fence.
        cleaned = cleaned.split("\n", 1)[-1] if "\n" in cleaned else cleaned
        if cleaned.endswith("```"):
            cleaned = cleaned[: -3]
        cleaned = cleaned.strip()
    return json.loads(cleaned)


def _questions_of(parsed: Any) -> list[dict[str, Any]]:
    """Pull the ``questions`` list out of a parsed payload, tolerating shapes."""
    if isinstance(parsed, dict):
        questions = parsed.get("questions", [])
    elif isinstance(parsed, list):
        questions = parsed
    else:
        questions = []
    return [q for q in questions if isinstance(q, dict)]


def _artefact_dict(a: GeneratedArtefact) -> dict[str, Any]:
    """Flatten a ``GeneratedArtefact`` to a JSON-friendly dict for API/storage."""
    return {
        "kind": a.kind,
        "topic": a.topic,
        "title": a.title,
        "body": a.body,
        "data": a.data,
        "grounding": a.grounding,
    }
