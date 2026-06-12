"""AI Gateway (#4) — the controlled chokepoint for all LLM access.

Responsibilities (built in slices):
- per-tenant quotas / rate-limits  (quota.py)        ✔ slice 1
- usage + cost ledger              (usage.py)        ✔ slice 1
- model routing per tenant/purpose (router.py)       — slice 2
- versioned prompt registry        (prompts.py)      — slice 3
- AIGateway facade tying it together (service.py)    — slice 4

Application/wrapper code depends on this package, never on a concrete
provider. Wrappers vendor a pinned snapshot of core, so additions here are
non-breaking until a wrapper chooses to re-vendor.
"""

from faastlab_askai_core.gateway.context import GatewayContext
from faastlab_askai_core.gateway.prompts import (
    PromptRecord,
    PromptRegistry,
    PromptSummary,
    PromptVersion,
    register_default,
    render_template,
)
from faastlab_askai_core.gateway.quota import (
    QuotaLimits,
    QuotaService,
    QuotaStatus,
    QuotaUsage,
    resolve_limits,
)
from faastlab_askai_core.gateway.router import (
    KNOWN_PROVIDERS,
    ModelRoute,
    ModelRouter,
    load_tenant_settings,
    resolve_route,
)
from faastlab_askai_core.gateway.service import AIGateway, GatewayResult
from faastlab_askai_core.gateway.usage import (
    UsageRecord,
    estimate_cost_usd,
    estimate_tokens,
    record_usage,
    usage_from_text,
)

__all__ = [
    "KNOWN_PROVIDERS",
    "AIGateway",
    "GatewayContext",
    "GatewayResult",
    "ModelRoute",
    "ModelRouter",
    "PromptRecord",
    "PromptRegistry",
    "PromptSummary",
    "PromptVersion",
    "QuotaLimits",
    "QuotaService",
    "QuotaStatus",
    "QuotaUsage",
    "UsageRecord",
    "estimate_cost_usd",
    "estimate_tokens",
    "load_tenant_settings",
    "record_usage",
    "register_default",
    "render_template",
    "resolve_limits",
    "resolve_route",
    "usage_from_text",
]
