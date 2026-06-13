"""Compliance-training generators + grader (#7).

Fakes search + gateway (no DB, no model) to verify:
* every generator grounds on retrieved corpus passages and carries citations;
* JSON artefacts parse (incl. a ```json code fence) and degrade to empty on
  malformed model output rather than raising;
* the scenario generator returns its story / conversation / reporting shape;
* the rubric grader clamps awarded points to [0, max] so a model can't inflate;
* a missing rubric reports ``needs_rubric`` instead of crashing.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from uuid import uuid4

from faastlab_askai_askai.training import TrainingGenerator, TrainingGrader
from faastlab_askai_search.retrievers.base import RetrievedChunk


def _chunk(title: str = "FCA SYSC") -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=uuid4(),
        document_id=uuid4(),
        tenant_id=uuid4(),
        document_title=title,
        content="Staff must report suspicions of money laundering to the MLRO.",
        score=0.9,
        rank=1,
        page_number=12,
    )


class _FakeSearch:
    """Returns fixed hits and records whether retrieval was metered."""

    def __init__(self, hits):
        self._hits = hits
        self.meter_seen = None

    async def search(self, *, tenant_id, query, k, filters=None, rerank=True, meter=True):
        self.meter_seen = meter
        return SimpleNamespace(hits=self._hits, confidence=0.5, latency_ms=1.0, query=query)


class _FakeGateway:
    """Returns a canned completion; captures the purpose it was called with."""

    def __init__(self, text: str):
        self._text = text
        self.purposes: list[str] = []
        self.seen_prompt = None

    async def complete(self, ctx, messages, *, temperature=0.0, max_tokens=None):
        self.purposes.append(ctx.purpose)
        self.seen_prompt = "\n".join(m.content for m in messages)
        return SimpleNamespace(text=self._text)


def _gen(text: str, hits=None):
    search = _FakeSearch(hits if hits is not None else [_chunk()])
    gw = _FakeGateway(text)
    return TrainingGenerator(search=search, gateway=gw), search, gw


# ---- Generators -------------------------------------------------------------


async def test_lesson_is_grounded_and_metered_as_training() -> None:
    gen, search, gw = _gen("# Money laundering\nStaff must report to the MLRO.")
    art = await gen.generate_lesson(tenant_id=uuid4(), topic="money laundering")
    assert art.kind == "lesson"
    assert "MLRO" in art.body
    # Grounding carries citations back to the source document.
    assert art.grounding["citations"][0]["document_title"] == "FCA SYSC"
    # Routed as training spend; retrieval not double-billed as a search.
    assert gw.purposes == ["training"]
    assert search.meter_seen is False


async def test_quiz_parses_questions() -> None:
    payload = json.dumps(
        {
            "questions": [
                {
                    "question": "Who do you report to?",
                    "options": ["CEO", "MLRO", "FCA", "Police"],
                    "answer_index": 1,
                    "rationale": "The MLRO receives internal SARs.",
                }
            ]
        }
    )
    gen, _, _ = _gen(payload)
    art = await gen.generate_quiz(tenant_id=uuid4(), topic="AML", num_questions=1)
    assert art.kind == "quiz"
    assert art.data["questions"][0]["answer_index"] == 1


async def test_quiz_tolerates_code_fence() -> None:
    payload = '```json\n{"questions": [{"question": "Q", "options": ["a","b"], "answer_index": 0, "rationale": "r"}]}\n```'
    gen, _, _ = _gen(payload)
    art = await gen.generate_quiz(tenant_id=uuid4(), topic="AML")
    assert len(art.data["questions"]) == 1


async def test_quiz_degrades_on_malformed_json() -> None:
    gen, _, _ = _gen("not json at all")
    art = await gen.generate_quiz(tenant_id=uuid4(), topic="AML")
    assert art.data["questions"] == []  # empty, not an exception


async def test_exam_passes_example_questions_into_prompt() -> None:
    gen, _, gw = _gen(json.dumps({"questions": []}))
    await gen.generate_exam(
        tenant_id=uuid4(),
        topic="AML",
        example_questions="Q1. Define a SAR. (10 marks)",
        difficulty="hard",
    )
    assert "PAST / SAMPLE EXAM QUESTIONS" in gw.seen_prompt
    assert "difficulty level: hard" in gw.seen_prompt


async def test_scenario_returns_story_shape() -> None:
    payload = json.dumps(
        {
            "title": "The unusual cash deposit",
            "narrative": "A new client wants to deposit £40,000 in cash...",
            "situation": "You are the account handler.",
            "conversation": [
                {"speaker": "Client", "line": "I'd rather not show ID.", "red_flag": True, "note": "Reluctance to provide ID."}
            ],
            "red_flags": ["Reluctance to provide ID", "Large cash with no rationale"],
            "reporting_steps": ["Raise an internal SAR to the MLRO [FCA SYSC]."],
            "questions": [{"question": "What do you do?", "model_answer": "File a SAR.", "marks": 10}],
        }
    )
    gen, _, gw = _gen(payload)
    art = await gen.generate_scenario(tenant_id=uuid4(), topic="money laundering", role="cashier")
    assert art.kind == "scenario"
    assert art.data["conversation"][0]["red_flag"] is True
    assert "MLRO" in art.data["reporting_steps"][0]
    assert art.data["questions"][0]["marks"] == 10
    assert "cashier" in gw.seen_prompt


async def test_blended_module_has_lesson_quiz_scenario() -> None:
    # The fake returns the same text for every call; valid for lesson (prose)
    # and parses as empty questions for quiz/scenario — shape is what we assert.
    gen, _, gw = _gen(json.dumps({"questions": []}))
    module = await gen.generate_blended(
        tenant_id=uuid4(), topic="AML", include_scenario=True
    )
    assert set(module) >= {"topic", "lesson", "quiz", "scenario"}
    # Lesson + quiz + scenario = three governed training completions.
    assert gw.purposes == ["training", "training", "training"]


# ---- Grader -----------------------------------------------------------------


def _grader(text: str):
    gw = _FakeGateway(text)
    return TrainingGrader(gateway=gw), gw


async def test_grader_clamps_to_max_points() -> None:
    # Model tries to award 999 on a criterion capped at 10 → clamped to 10.
    grader, _ = _grader(json.dumps([{"key": "knowledge", "points": 999, "comment": "ok"}]))
    result = await grader.grade(
        tenant_id=uuid4(),
        content="My answer.",
        criteria=[{"key": "knowledge", "description": "Knows the rule", "max_points": 10}],
        pass_mark_pct=70,
    )
    assert result.status == "complete"
    assert result.total_score == 10.0
    assert result.max_score == 10.0
    assert result.passed is True


async def test_grader_needs_rubric_when_empty() -> None:
    grader, gw = _grader("[]")
    result = await grader.grade(tenant_id=uuid4(), content="x", criteria=[])
    assert result.status == "needs_rubric"
    assert gw.purposes == []  # no model call when there's nothing to grade


async def test_grader_fail_below_pass_mark() -> None:
    grader, _ = _grader(json.dumps([{"key": "k", "points": 3, "comment": "weak"}]))
    result = await grader.grade(
        tenant_id=uuid4(),
        content="weak answer",
        criteria=[{"key": "k", "description": "d", "max_points": 10}],
        pass_mark_pct=70,
    )
    assert result.passed is False
    assert result.status == "complete"
