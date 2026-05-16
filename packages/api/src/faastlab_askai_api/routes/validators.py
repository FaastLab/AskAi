"""Validator endpoints — list rule packs + run a rule-pack validation."""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from faastlab_askai_core.adapters import Principal
from faastlab_askai_core.db import Document, get_sessionmaker
from faastlab_askai_validators.rule_pack_validator import RulePackValidator
from faastlab_askai_validators.rule_packs import get_pack, list_packs

from faastlab_askai_api.audit_helper import record_action
from faastlab_askai_api.middleware.principal import get_principal
from faastlab_askai_api.middleware.trial import (
    require_active_trial_or_subscription,
)
from faastlab_askai_api.routes.ask import _require_byok_if_configured

log = logging.getLogger(__name__)

router = APIRouter(tags=["validators"], prefix="/validators")
_pipeline = RulePackValidator()


class RuleRequirementOut(BaseModel):
    id: str
    title: str
    description: str
    citation: str
    severity: str


class RulePackOut(BaseModel):
    id: str
    regulator: str
    name: str
    version: str
    summary: str
    requirements: list[RuleRequirementOut]


@router.get("/packs", response_model=list[RulePackOut])
async def get_packs(
    _: Principal = Depends(get_principal),
) -> list[RulePackOut]:
    """Return all available rule packs — metadata only, no scoring."""
    return [
        RulePackOut(
            id=p.id,
            regulator=p.regulator,
            name=p.name,
            version=p.version,
            summary=p.summary,
            requirements=[
                RuleRequirementOut(
                    id=r.id,
                    title=r.title,
                    description=r.description,
                    citation=r.citation,
                    severity=r.severity,
                )
                for r in p.requirements
            ],
        )
        for p in list_packs()
    ]


class ValidateRequest(BaseModel):
    document_id: UUID
    pack_id: str


class RequirementResultOut(BaseModel):
    requirement_id: str
    title: str
    citation: str
    severity: str
    verdict: str
    rationale: str
    evidence_excerpts: list[dict[str, Any]]


class ValidateReportOut(BaseModel):
    pack_id: str
    pack_name: str
    pack_version: str
    document_id: str
    document_title: str
    overall: str
    score: float
    counts: dict[str, int]
    requirements: list[RequirementResultOut]
    generated_at: str
    latency_ms: float


@router.post("/run", response_model=ValidateReportOut)
async def run_validation(
    body: ValidateRequest,
    principal: Principal = Depends(require_active_trial_or_subscription),
) -> ValidateReportOut:
    """Score a document against a rule pack."""
    _require_byok_if_configured()
    if get_pack(body.pack_id) is None:
        raise HTTPException(status_code=404, detail=f"unknown pack: {body.pack_id}")

    # Resolve the document so we know its title (and confirm tenant ownership).
    sm = get_sessionmaker()
    async with sm() as session:
        result = await session.execute(
            select(Document).where(
                (Document.id == body.document_id)
                & (Document.tenant_id == principal.tenant_id)
            )
        )
        doc = result.scalar_one_or_none()
    if doc is None:
        raise HTTPException(status_code=404, detail="document not found")

    report = await _pipeline.validate(
        tenant_id=principal.tenant_id,
        document_id=body.document_id,
        document_title=doc.title,
        pack_id=body.pack_id,
    )

    await record_action(
        principal=principal,
        action="validate",
        resource="/v1/validators/run",
        query=f"Validate \"{doc.title}\" against {report.pack_name}",
        response_summary=(
            f"{report.overall.upper()} — score {(report.score*100):.0f}% "
            f"({report.counts.get('green',0)} green, "
            f"{report.counts.get('amber',0)} amber, "
            f"{report.counts.get('red',0)} red)"
        ),
        sources=[
            {
                "requirement_id": r.requirement_id,
                "title": r.title,
                "verdict": r.verdict,
                "citation": r.citation,
            }
            for r in report.requirements
        ],
        latency_ms=report.latency_ms,
        extra={
            "pack_id": report.pack_id,
            "document_id": report.document_id,
        },
    )

    return ValidateReportOut(
        pack_id=report.pack_id,
        pack_name=report.pack_name,
        pack_version=report.pack_version,
        document_id=report.document_id,
        document_title=report.document_title,
        overall=report.overall,
        score=report.score,
        counts=report.counts,
        requirements=[
            RequirementResultOut(
                requirement_id=r.requirement_id,
                title=r.title,
                citation=r.citation,
                severity=r.severity,
                verdict=r.verdict,
                rationale=r.rationale,
                evidence_excerpts=r.evidence_excerpts,
            )
            for r in report.requirements
        ],
        generated_at=report.generated_at.isoformat(),
        latency_ms=round(report.latency_ms, 1),
    )
