"""Tests for assistant roles: name/slug helpers, registration, and the
system-prompt resolution order (explicit role -> tenant default -> rag.system)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

from faastlab_askai_askai.prompts import (
    builtin_role_labels,
    role_prompt_name,
    role_slug_from_name,
)
from faastlab_askai_askai.prompts.rag import RAG_SYSTEM_PROMPT
from faastlab_askai_askai.service import AskAiService
from faastlab_askai_core.gateway.prompts import _DEFAULTS

# ---- name/slug helpers ------------------------------------------------------


def test_role_name_slug_roundtrip() -> None:
    assert role_prompt_name("compliance-officer") == "role.compliance-officer"
    assert role_slug_from_name("role.compliance-officer") == "compliance-officer"
    assert role_slug_from_name("rag.system") is None  # not a role prompt


def test_role_name_normalises_case_and_whitespace() -> None:
    assert role_prompt_name("  Compliance-Officer ") == "role.compliance-officer"


def test_builtin_roles_registered_as_defaults() -> None:
    labels = builtin_role_labels()
    assert "compliance-officer" in labels and "general" in labels
    for slug in labels:
        assert role_prompt_name(slug) in _DEFAULTS  # resolvable with no DB row


def test_general_role_is_the_standard_rag_prompt() -> None:
    # 'general' must reuse rag.system's text so default behaviour is unchanged.
    assert _DEFAULTS[role_prompt_name("general")] == RAG_SYSTEM_PROMPT


# ---- resolution order -------------------------------------------------------


def _service(known: set[str]) -> AskAiService:
    """A service whose registry only knows `known` prompt names (template =
    'PROMPT::<name>'), with DB-free deps."""

    class FakeRegistry:
        async def get(self, name: str):
            if name in known:
                return SimpleNamespace(template=f"PROMPT::{name}")
            raise KeyError(name)

    svc = AskAiService(search=AsyncMock(), gateway=AsyncMock(), memory=AsyncMock())
    svc._prompts = FakeRegistry()  # type: ignore[assignment]
    return svc


async def test_explicit_role_wins() -> None:
    svc = _service({"role.auditor", "rag.system"})
    svc._tenant_default_role = AsyncMock(return_value="general")  # type: ignore[method-assign]
    out = await svc._system_prompt(tenant_id=uuid4(), role="auditor")
    assert out == "PROMPT::role.auditor"


async def test_unknown_explicit_role_falls_to_tenant_default() -> None:
    svc = _service({"role.auditor", "rag.system"})
    svc._tenant_default_role = AsyncMock(return_value="auditor")  # type: ignore[method-assign]
    out = await svc._system_prompt(tenant_id=uuid4(), role="does-not-exist")
    assert out == "PROMPT::role.auditor"


async def test_no_role_uses_tenant_default() -> None:
    svc = _service({"role.legal", "rag.system"})
    svc._tenant_default_role = AsyncMock(return_value="legal")  # type: ignore[method-assign]
    out = await svc._system_prompt(tenant_id=uuid4(), role=None)
    assert out == "PROMPT::role.legal"


async def test_falls_back_to_rag_system_when_no_role() -> None:
    svc = _service({"rag.system"})
    svc._tenant_default_role = AsyncMock(return_value=None)  # type: ignore[method-assign]
    out = await svc._system_prompt(tenant_id=uuid4(), role=None)
    assert out == "PROMPT::rag.system"
