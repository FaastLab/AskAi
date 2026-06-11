"""Model router — resolves (provider, model) per tenant + purpose.

A single place that answers "which model serves THIS call?", so the answer
can vary by:
  - purpose: chat / validate use the high-quality model; summarise uses the
    cheaper-faster tier; embed uses the embeddings model.
  - tenant: a tenant may pin its own model via
    tenant.settings["gateway"]["models"][purpose].

Resolution order (first match wins):
  1. tenant override  tenant.settings["gateway"]["models"][purpose]
  2. global default for the purpose (from Settings)

A tenant override may be just a model name ("gpt-4o") — provider inherited —
or "provider:model" ("ollama:qwen2.5:32b") to also switch provider. This is
how a sovereign deployment routes one noisy tenant to a cheaper local model
without touching anyone else.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import select

from faastlab_askai_core.config import get_settings
from faastlab_askai_core.db import Tenant, get_sessionmaker
from faastlab_askai_core.gateway.context import GatewayContext

# Known provider prefixes — used to decide whether a "x:y" override names a
# provider or is just a model id that happens to contain a colon (e.g. the
# Ollama tag "qwen2.5:32b"). Union of the LLM + embeddings provider literals.
KNOWN_PROVIDERS = frozenset(
    {"openai", "azure", "anthropic", "bedrock", "ollama", "cohere", "huggingface"}
)


@dataclass(frozen=True, slots=True)
class ModelRoute:
    provider: str
    model: str
    purpose: str


def _defaults_for(purpose: str, s: Any) -> tuple[str, str]:
    """Global (provider, model) default for a purpose, from Settings."""
    if purpose == "embed":
        return s.embeddings_provider, s.embeddings_model
    if purpose == "summarise":
        return s.llm_provider, s.summarisation_model
    # chat, validate, and any unknown purpose fall back to the answer model.
    return s.llm_provider, s.llm_model


def _parse_override(override: str, default_provider: str) -> tuple[str, str]:
    """Split a "provider:model" override, else treat it all as a model id.

    Only splits when the prefix is a recognised provider, so model ids that
    contain a colon (Ollama tags) are preserved intact.
    """
    head, sep, tail = override.partition(":")
    if sep and head in KNOWN_PROVIDERS and tail:
        return head, tail
    return default_provider, override


def resolve_route(
    tenant_settings: dict[str, Any] | None,
    purpose: str,
    settings: Any = None,
) -> ModelRoute:
    """Pure resolution — no I/O. Used directly in tests and by ModelRouter."""
    s = settings or get_settings()
    provider, model = _defaults_for(purpose, s)

    override: Any = None
    if tenant_settings:
        models = (tenant_settings.get("gateway") or {}).get("models") or {}
        override = models.get(purpose)
    if override:
        provider, model = _parse_override(str(override), provider)

    return ModelRoute(provider=provider, model=model, purpose=purpose)


async def load_tenant_settings(tenant_id: UUID) -> dict[str, Any] | None:
    """Load a tenant's `settings` JSON (or None). Shared by the router and the
    AIGateway facade so both read the row the same way."""
    sm = get_sessionmaker()
    async with sm() as session:
        return (
            await session.execute(
                select(Tenant.settings).where(Tenant.id == tenant_id)
            )
        ).scalar_one_or_none()


class ModelRouter:
    """Resolves a ModelRoute for a call. Stateless; share one instance."""

    async def route(
        self,
        ctx: GatewayContext,
        tenant_settings: dict[str, Any] | None = None,
    ) -> ModelRoute:
        """Resolve the route for `ctx`. Pass `tenant_settings` to avoid a DB
        round-trip when the caller already loaded the tenant row."""
        if tenant_settings is None:
            tenant_settings = await load_tenant_settings(ctx.tenant_id)
        return resolve_route(tenant_settings, ctx.purpose)
