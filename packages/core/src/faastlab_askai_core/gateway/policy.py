"""Policy engine (#6) — per-tenant governance over what the AI may do.

A simple, declarative policy stored on the tenant row
(`tenant.settings["gateway"]["policy"]`) and enforced at the AI-gateway
chokepoint BEFORE any model call:
  - enabled:                 master switch; False suspends ALL AI for the tenant.
  - allowed_models:          optional whitelist; empty = any routed model is ok.
  - max_tokens_per_request:  hard cap on generation length (0 = no cap).
  - allow_cloud:             data-egress guardrail. False = NO request may leave
                             the sovereign stack — the gateway drops every cloud
                             (non-sovereign) target, so this tenant's prompts can
                             never reach OpenAI, even via failover.

This is the "what the AI may / may not do" layer an enterprise security review
asks for. Defaults are permissive (enabled, no model restriction, no cap) so
turning governance on never breaks an existing tenant until an owner sets a
restriction. Same shape as the quota config, so both live under
`settings["gateway"]`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from faastlab_askai_core.exceptions import PolicyViolation


@dataclass(frozen=True, slots=True)
class Policy:
    enabled: bool = True
    allowed_models: tuple[str, ...] = ()
    max_tokens_per_request: int = 0  # 0 = no cap
    # Data-egress guardrail. True (default) preserves today's behaviour; False
    # forbids any non-sovereign (cloud) target — the sovereignty lock.
    allow_cloud: bool = True

    @property
    def has_restrictions(self) -> bool:
        return (
            not self.enabled
            or bool(self.allowed_models)
            or self.max_tokens_per_request > 0
            or not self.allow_cloud
        )


def _coerce_int(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def resolve_policy(tenant_settings: dict[str, Any] | None) -> Policy:
    """Build a Policy from a tenant's settings JSON (permissive defaults)."""
    p: dict[str, Any] = {}
    if tenant_settings:
        p = (tenant_settings.get("gateway") or {}).get("policy") or {}
    models = p.get("allowed_models") or []
    return Policy(
        enabled=bool(p.get("enabled", True)),
        allowed_models=tuple(str(m).strip() for m in models if str(m).strip()),
        max_tokens_per_request=_coerce_int(p.get("max_tokens_per_request")),
        allow_cloud=bool(p.get("allow_cloud", True)),
    )


class PolicyEngine:
    """Stateless enforcement; share one instance."""

    def enforce(self, policy: Policy, *, model: str | None) -> None:
        """Raise PolicyViolation if the call is disallowed. Token capping is a
        clamp (not a rejection) — see `effective_max_tokens`."""
        if not policy.enabled:
            raise PolicyViolation(
                "AI access is suspended for this tenant by policy."
            )
        if (
            policy.allowed_models
            and model is not None
            and model not in policy.allowed_models
        ):
            raise PolicyViolation(
                f"Model {model!r} is not on this tenant's allowed-models list."
            )

    def effective_max_tokens(
        self, policy: Policy, requested: int | None
    ) -> int | None:
        """Clamp the requested max_tokens down to the policy cap (if any)."""
        cap = policy.max_tokens_per_request
        if cap <= 0:
            return requested
        return cap if requested is None else min(requested, cap)
