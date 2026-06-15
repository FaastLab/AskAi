"""Model targets + routing chain — the "which model(s), in what order" config.

A **target** is a concrete place to send a completion: a (base_url, api_key,
model) triple. Two are defined from settings:

  * ``qwen``   — the sovereign vLLM endpoint (llm_base_url + llm_model)
  * ``openai`` — OpenAI cloud (openai_cloud_base_url=None → api.openai.com)

Both speak the OpenAI-compatible API, so they share the OpenAI adapter and only
differ by endpoint + model. A tenant picks an **ordered chain** of targets in
``tenant.settings["gateway"]["routing"]``:

  * ``["qwen", "openai"]`` → Qwen primary, fail over to OpenAI if Qwen is down
  * ``["qwen"]``           → Qwen only, no failover (fails if unreachable)
  * ``["openai"]``         → OpenAI only, no failover

The gateway tries the chain in order, failing over ONLY when a target errors
(see AIGateway). With a single-element chain there is nothing to fail over to,
so the error propagates — exactly the requested behaviour.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from faastlab_askai_core.config import get_settings

# The canonical target names a tenant can choose from, in display order.
TARGET_NAMES = ("qwen", "openai")


@dataclass(frozen=True, slots=True)
class ModelTarget:
    name: str  # "qwen" | "openai"
    label: str
    provider: str  # "openai" — both are OpenAI-compatible
    model: str
    base_url: str | None
    api_key: str | None
    configured: bool  # is this target actually usable (endpoint/key present)?
    # True = runs on our own sovereign infra (data never leaves). False = a
    # cloud endpoint (OpenAI) — gated by the policy's allow_cloud flag.
    sovereign: bool


def available_targets(settings: Any = None) -> dict[str, ModelTarget]:
    """The targets this deployment knows about, built from settings.

    ``configured`` flags whether a target can actually be called: Qwen needs a
    sovereign ``llm_base_url``; OpenAI cloud needs an ``openai_api_key``. The UI
    uses it to disable a target the operator hasn't set up.
    """
    s = settings or get_settings()
    return {
        "qwen": ModelTarget(
            name="qwen",
            label="Qwen (sovereign)",
            provider="openai",
            model=s.llm_model,
            base_url=s.llm_base_url,
            # vLLM ignores the key, but the SDK requires a non-empty string.
            api_key=s.openai_api_key or "sk-sovereign-local",
            configured=bool(s.llm_base_url),
            sovereign=True,  # our own vLLM box — data stays on-prem
        ),
        "openai": ModelTarget(
            name="openai",
            label="OpenAI (cloud)",
            provider="openai",
            model=s.openai_cloud_model,
            base_url=s.openai_cloud_base_url,  # None → api.openai.com
            api_key=s.openai_api_key,
            configured=bool(s.openai_api_key),
            sovereign=False,  # leaves our infra → gated by policy.allow_cloud
        ),
    }


def _default_order(s: Any) -> list[str]:
    """With no tenant choice, prefer the sovereign target if it's configured,
    else fall back to cloud — so existing deployments behave as before."""
    return ["qwen"] if s.llm_base_url else ["openai"]


def resolve_target_chain(
    tenant_settings: dict[str, Any] | None, settings: Any = None
) -> list[ModelTarget]:
    """Ordered list of targets to try for a call (primary first).

    Reads ``tenant.settings["gateway"]["routing"]`` (a list of target names).
    Unknown names are dropped; an empty/missing config uses the deployment
    default. Always returns at least one target.
    """
    s = settings or get_settings()
    avail = available_targets(s)

    order: list[str] | None = None
    if tenant_settings:
        raw = (tenant_settings.get("gateway") or {}).get("routing")
        if isinstance(raw, list):
            order = [str(n) for n in raw]
    if not order:
        order = _default_order(s)

    chain = [avail[name] for name in order if name in avail]
    if not chain:
        # Misconfigured to all-unknown names — degrade to the default.
        chain = [avail[name] for name in _default_order(s) if name in avail]
    return chain
