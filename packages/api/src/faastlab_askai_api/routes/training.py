"""Compliance-training routes (#7) — generate → assign → submit → grade → record.

The mandatory-control loop for a regulated firm: generate corpus-grounded
training on the *current* rules, assign it to staff, capture their submission,
grade it (deterministically for MCQs, by rubric for free text), and write an
audit-grade ``TrainingRecord`` proving who was trained on what and whether they
passed.

Generation and grading are governed like ``/v1/ask`` — trial + quota + policy,
``purpose="training"`` / ``"grading"`` — so they're metered and stay on the
sovereign stack. Management endpoints (list/assign/records) are plain
tenant-scoped reads/writes behind ``get_principal``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from faastlab_askai_api.audit_helper import record_action
from faastlab_askai_api.middleware.policy import enforce_policy
from faastlab_askai_api.middleware.principal import get_principal
from faastlab_askai_api.middleware.quota import enforce_quota
from faastlab_askai_api.middleware.trial import require_active_trial_or_subscription
from faastlab_askai_api.routes.ask import _require_byok_if_configured
from faastlab_askai_askai.training import TrainingGenerator, TrainingGrader
from faastlab_askai_core.adapters import Principal
from faastlab_askai_core.db import (
    TrainingAssignment,
    TrainingModule,
    TrainingRecord,
    get_sessionmaker,
)

router = APIRouter(tags=["training"])

# Stateless services — construct once, share across requests (like the other
# routes' singletons). Both wrap SearchService + AIGateway internally.
_generator = TrainingGenerator()
_grader = TrainingGrader()

# Generators we expose, mapped to the kind string the UI sends.
_ARTEFACT_KINDS = {
    "lesson",
    "revision_guide",
    "quiz",
    "exam",
    "flashcards",
    "slides",
    "scenario",
    "blended",
}


# ---- Request / response models ----------------------------------------------


class GenerateRequest(BaseModel):
    topic: str = Field(min_length=1, max_length=2000)
    kind: str = Field(default="blended")
    num_questions: int = Field(default=5, ge=1, le=20)
    style: str = "mixed"
    difficulty: str = "mixed"
    example_questions: str | None = Field(default=None, max_length=8000)
    objectives: list[str] | None = None
    role: str | None = Field(default=None, max_length=200)
    include_scenario: bool = True


class ModuleCreate(BaseModel):
    title: str = Field(min_length=1, max_length=512)
    topic: str = Field(min_length=1, max_length=2000)
    kind: str = "blended"
    content: dict[str, Any] = Field(default_factory=dict)
    rubric: dict[str, Any] = Field(default_factory=dict)
    grounding: dict[str, Any] = Field(default_factory=dict)
    source_document_ids: list[str] = Field(default_factory=list)
    pass_mark_pct: float = Field(default=70.0, ge=0, le=100)


class ModuleRead(BaseModel):
    id: UUID
    title: str
    topic: str
    kind: str
    content: dict[str, Any]
    rubric: dict[str, Any]
    grounding: dict[str, Any]
    source_document_ids: list[str]
    pass_mark_pct: float
    created_by: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class AssignRequest(BaseModel):
    module_id: UUID
    user_ids: list[str] = Field(min_length=1)
    due_at: datetime | None = None


class AssignmentRead(BaseModel):
    id: UUID
    module_id: UUID
    user_id: str
    assigned_by: str | None
    status: str
    due_at: datetime | None
    completed_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class SubmitRequest(BaseModel):
    module_id: UUID
    assignment_id: UUID | None = None
    # MCQ path: the learner's selected option index per question.
    answers: list[int] | None = None
    # Free-text path: a written answer graded against the module rubric.
    content: str | None = None


class RecordRead(BaseModel):
    id: UUID
    module_id: UUID
    assignment_id: UUID | None
    user_id: str
    topic: str
    score: float | None
    max_score: float | None
    score_pct: float | None
    passed: bool | None
    grade_detail: dict[str, Any]
    completed_at: datetime

    model_config = {"from_attributes": True}


# ---- Generation (governed, metered) -----------------------------------------


@router.post("/training/generate")
async def generate_training(
    body: GenerateRequest,
    request: Request,
    principal: Principal = Depends(require_active_trial_or_subscription),
    _quota: Principal = Depends(enforce_quota("training")),
    _policy: Principal = Depends(enforce_policy("training")),
) -> dict[str, Any]:
    """Generate corpus-grounded training content (not persisted).

    Returns a single artefact, or — for ``kind="blended"`` — a module dict with
    a lesson, quiz and scenario. Persist it afterwards via ``POST
    /training/modules`` if you want to assign it.
    """
    if body.kind not in _ARTEFACT_KINDS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"kind must be one of: {', '.join(sorted(_ARTEFACT_KINDS))}",
        )
    _require_byok_if_configured()
    request_id = request.headers.get("x-request-id") or uuid4().hex
    common = {
        "tenant_id": principal.tenant_id,
        "topic": body.topic,
        "user_id": principal.user_id,
        "request_id": request_id,
    }

    if body.kind == "blended":
        result = await _generator.generate_blended(
            objectives=body.objectives,
            num_questions=body.num_questions,
            include_scenario=body.include_scenario,
            **common,
        )
    elif body.kind == "lesson":
        result = _artefact_dict(
            await _generator.generate_lesson(objectives=body.objectives, **common)
        )
    elif body.kind == "revision_guide":
        result = _artefact_dict(await _generator.generate_revision_guide(**common))
    elif body.kind == "quiz":
        result = _artefact_dict(
            await _generator.generate_quiz(num_questions=body.num_questions, **common)
        )
    elif body.kind == "exam":
        result = _artefact_dict(
            await _generator.generate_exam(
                num_questions=body.num_questions,
                style=body.style,
                difficulty=body.difficulty,
                example_questions=body.example_questions,
                **common,
            )
        )
    elif body.kind == "flashcards":
        result = _artefact_dict(
            await _generator.generate_flashcards(num_cards=body.num_questions * 2, **common)
        )
    elif body.kind == "slides":
        result = _artefact_dict(await _generator.generate_slides(**common))
    else:  # scenario
        result = _artefact_dict(
            await _generator.generate_scenario(
                role=body.role, num_questions=body.num_questions, **common
            )
        )

    await record_action(
        principal=principal,
        action="training.generate",
        resource="/v1/training/generate",
        query=body.topic,
        response_summary=f"generated {body.kind}",
        extra={"request_id": request_id, "kind": body.kind},
    )
    return {"kind": body.kind, "result": result}


# ---- Module persistence + listing -------------------------------------------


@router.post(
    "/training/modules", response_model=ModuleRead, status_code=status.HTTP_201_CREATED
)
async def create_module(
    body: ModuleCreate, principal: Principal = Depends(get_principal)
) -> TrainingModule:
    """Persist a generated module so it can be assigned and graded against."""
    module = TrainingModule(
        id=uuid4(),
        tenant_id=principal.tenant_id,
        title=body.title,
        topic=body.topic,
        kind=body.kind,
        content=body.content,
        rubric=body.rubric,
        grounding=body.grounding,
        source_document_ids=body.source_document_ids,
        pass_mark_pct=body.pass_mark_pct,
        created_by=principal.user_id,
    )
    async with get_sessionmaker()() as session:
        session.add(module)
        await session.commit()
        await session.refresh(module)
    await record_action(
        principal=principal,
        action="training.module.create",
        resource=f"/v1/training/modules/{module.id}",
        query=body.topic,
        extra={"module_id": str(module.id), "kind": body.kind},
    )
    return module


@router.get("/training/modules", response_model=list[ModuleRead])
async def list_modules(
    principal: Principal = Depends(get_principal),
) -> list[TrainingModule]:
    async with get_sessionmaker()() as session:
        rows = await session.execute(
            select(TrainingModule)
            .where(TrainingModule.tenant_id == principal.tenant_id)
            .order_by(TrainingModule.created_at.desc())
        )
        return list(rows.scalars().all())


@router.get("/training/modules/{module_id}", response_model=ModuleRead)
async def get_module(
    module_id: UUID, principal: Principal = Depends(get_principal)
) -> TrainingModule:
    module = await _load_module(module_id, principal.tenant_id)
    return module


# ---- Assignment -------------------------------------------------------------


@router.post(
    "/training/assignments",
    response_model=list[AssignmentRead],
    status_code=status.HTTP_201_CREATED,
)
async def assign_module(
    body: AssignRequest, principal: Principal = Depends(get_principal)
) -> list[TrainingAssignment]:
    """Assign a module to one or more staff members."""
    await _load_module(body.module_id, principal.tenant_id)  # ownership check
    assignments = [
        TrainingAssignment(
            id=uuid4(),
            tenant_id=principal.tenant_id,
            module_id=body.module_id,
            user_id=uid,
            assigned_by=principal.user_id,
            status="assigned",
            due_at=body.due_at,
        )
        for uid in dict.fromkeys(body.user_ids)  # de-dup, preserve order
    ]
    async with get_sessionmaker()() as session:
        session.add_all(assignments)
        await session.commit()
        for a in assignments:
            await session.refresh(a)
    await record_action(
        principal=principal,
        action="training.assign",
        resource=f"/v1/training/modules/{body.module_id}",
        extra={"module_id": str(body.module_id), "count": len(assignments)},
    )
    return assignments


@router.get("/training/assignments", response_model=list[AssignmentRead])
async def list_assignments(
    principal: Principal = Depends(get_principal),
    user_id: str | None = None,
    mine: bool = False,
) -> list[TrainingAssignment]:
    """List assignments for the tenant; ``mine=true`` or ``user_id=`` to filter."""
    target = principal.user_id if mine else user_id
    async with get_sessionmaker()() as session:
        stmt = select(TrainingAssignment).where(
            TrainingAssignment.tenant_id == principal.tenant_id
        )
        if target is not None:
            stmt = stmt.where(TrainingAssignment.user_id == target)
        rows = await session.execute(stmt.order_by(TrainingAssignment.created_at.desc()))
        return list(rows.scalars().all())


# ---- Submit + grade + record (governed) -------------------------------------


@router.post("/training/submit", response_model=RecordRead)
async def submit_training(
    body: SubmitRequest,
    request: Request,
    principal: Principal = Depends(require_active_trial_or_subscription),
    _quota: Principal = Depends(enforce_quota("grading")),
    _policy: Principal = Depends(enforce_policy("grading")),
) -> TrainingRecord:
    """Grade a learner's submission and write an audit-grade training record.

    MCQ path (``answers``): graded deterministically against the stored
    ``answer_index`` — no LLM call, no metering. Free-text path (``content``):
    graded by the rubric grader through the governed gateway.
    """
    module = await _load_module(body.module_id, principal.tenant_id)
    request_id = request.headers.get("x-request-id") or uuid4().hex

    if body.answers is not None:
        graded = _grade_mcq(module, body.answers)
        submission_text = None
    elif body.content is not None:
        _require_byok_if_configured()
        result = await _grader.grade(
            tenant_id=principal.tenant_id,
            content=body.content,
            criteria=module.rubric,
            pass_mark_pct=module.pass_mark_pct,
            user_id=principal.user_id,
            request_id=request_id,
        )
        if result.status == "needs_rubric":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="This module has no rubric — submit MCQ answers instead.",
            )
        graded = {
            "score": result.total_score,
            "max_score": result.max_score,
            "score_pct": (
                round(result.total_score / result.max_score * 100, 1)
                if result.total_score is not None and result.max_score
                else None
            ),
            "passed": result.passed,
            "detail": {"scores": result.scores, "feedback": result.feedback},
        }
        submission_text = body.content
    else:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Provide either `answers` (MCQ) or `content` (free text).",
        )

    record = TrainingRecord(
        id=uuid4(),
        tenant_id=principal.tenant_id,
        module_id=module.id,
        assignment_id=body.assignment_id,
        user_id=principal.user_id,
        topic=module.topic,
        score=graded["score"],
        max_score=graded["max_score"],
        score_pct=graded["score_pct"],
        passed=graded["passed"],
        grade_detail=graded["detail"],
        submission=submission_text,
    )
    async with get_sessionmaker()() as session:
        session.add(record)
        # Mark the assignment complete if one was referenced.
        if body.assignment_id is not None:
            assignment = (
                await session.execute(
                    select(TrainingAssignment).where(
                        TrainingAssignment.id == body.assignment_id,
                        TrainingAssignment.tenant_id == principal.tenant_id,
                    )
                )
            ).scalar_one_or_none()
            if assignment is not None:
                assignment.status = "completed"
                assignment.completed_at = record.completed_at
        await session.commit()
        await session.refresh(record)

    await record_action(
        principal=principal,
        action="training.submit",
        resource=f"/v1/training/modules/{module.id}",
        query=module.topic,
        response_summary=(
            f"score={graded['score_pct']}% passed={graded['passed']}"
        ),
        extra={"request_id": request_id, "module_id": str(module.id)},
    )
    return record


@router.get("/training/records", response_model=list[RecordRead])
async def list_records(
    principal: Principal = Depends(get_principal),
    user_id: str | None = None,
    module_id: UUID | None = None,
) -> list[TrainingRecord]:
    """List training records (the audit trail) for the tenant, optionally filtered."""
    async with get_sessionmaker()() as session:
        stmt = select(TrainingRecord).where(
            TrainingRecord.tenant_id == principal.tenant_id
        )
        if user_id is not None:
            stmt = stmt.where(TrainingRecord.user_id == user_id)
        if module_id is not None:
            stmt = stmt.where(TrainingRecord.module_id == module_id)
        rows = await session.execute(stmt.order_by(TrainingRecord.completed_at.desc()))
        return list(rows.scalars().all())


# ---- Helpers ----------------------------------------------------------------


async def _load_module(module_id: UUID, tenant_id: UUID) -> TrainingModule:
    """Load a tenant's module or 404 — the single ownership-checked read."""
    async with get_sessionmaker()() as session:
        module = (
            await session.execute(
                select(TrainingModule).where(
                    TrainingModule.id == module_id,
                    TrainingModule.tenant_id == tenant_id,
                )
            )
        ).scalar_one_or_none()
    if module is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="training module not found"
        )
    return module


def _grade_mcq(module: TrainingModule, answers: list[int]) -> dict[str, Any]:
    """Deterministically score MCQ answers against the module's stored questions.

    Looks for a quiz (or exam) question list with ``answer_index`` in the
    module content. One mark per question; pass = pct ≥ the module pass mark.
    """
    questions = _mcq_questions(module.content)
    total = len(questions)
    if total == 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="This module has no auto-gradable questions.",
        )
    correct = 0
    detail: list[dict[str, Any]] = []
    for i, q in enumerate(questions):
        chosen = answers[i] if i < len(answers) else None
        expected = q.get("answer_index")
        is_correct = chosen is not None and chosen == expected
        correct += 1 if is_correct else 0
        detail.append(
            {
                "question": q.get("question", ""),
                "chosen": chosen,
                "expected": expected,
                "correct": is_correct,
                "rationale": q.get("rationale", ""),
            }
        )
    pct = round(correct / total * 100, 1)
    return {
        "score": float(correct),
        "max_score": float(total),
        "score_pct": pct,
        "passed": pct >= module.pass_mark_pct,
        "detail": {"answers": detail},
    }


def _mcq_questions(content: dict[str, Any]) -> list[dict[str, Any]]:
    """Find the MCQ question list in a module's content (quiz artefact or blended)."""
    # Blended module: questions live under content["quiz"]["data"]["questions"].
    quiz = content.get("quiz")
    if isinstance(quiz, dict):
        data = quiz.get("data", {})
        if isinstance(data, dict) and data.get("questions"):
            return [q for q in data["questions"] if isinstance(q, dict)]
    # Single quiz/exam artefact: content["data"]["questions"].
    data = content.get("data")
    if isinstance(data, dict) and data.get("questions"):
        return [q for q in data["questions"] if isinstance(q, dict)]
    # Raw shape: content["questions"].
    if content.get("questions"):
        return [q for q in content["questions"] if isinstance(q, dict)]
    return []


def _artefact_dict(a: Any) -> dict[str, Any]:
    """Flatten a GeneratedArtefact to a JSON-friendly dict."""
    return {
        "kind": a.kind,
        "topic": a.topic,
        "title": a.title,
        "body": a.body,
        "data": a.data,
        "grounding": a.grounding,
    }
