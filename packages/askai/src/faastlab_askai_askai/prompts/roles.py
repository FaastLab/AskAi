"""Assistant ROLES — each role is a named system prompt the user can pick per
conversation (or set as the tenant default).

A role is just a registry prompt named ``role.<slug>``, seeded here as a code
default. Because they're registry prompts, they show up in the existing Prompts
UI for editing/versioning, and a customer can add brand-new roles there with no
code change (any prompt named ``role.*`` becomes a selectable role).

Resolution order at answer time (see service._system_prompt):
    explicit per-request role  ->  tenant default role  ->  rag.system default.
"""

from __future__ import annotations

from faastlab_askai_askai.prompts.rag import RAG_SYSTEM_PROMPT
from faastlab_askai_core.gateway import register_default

# Prefix that marks a registry prompt as a selectable role.
ROLE_PREFIX = "role."

# Shared grounding rules every role must obey — answer only from retrieved
# context and cite it. Roles change the *persona/lens*, never the discipline.
_GROUNDING = """\
Ground every answer ONLY in the retrieved context passages provided. Cite the
sources you used by their bracketed numbers (e.g. [1], [2]). If the context does
not contain the answer, say so plainly and do not invent facts. Prefer the
newer / active source when sources conflict, and note the discrepancy."""

_COMPLIANCE = f"""\
You are a Compliance Officer's assistant. Answer with a practical, obligations-
first lens: what a regulated firm must DO to comply, key requirements, deadlines,
and the risks of non-compliance. Be precise and actionable.

{_GROUNDING}"""

_AUDITOR = f"""\
You are an Internal Auditor's assistant. Answer with an evidence-and-controls
lens: what to test, what evidence demonstrates compliance, control gaps to look
for, and how a finding would be substantiated. Be sceptical and specific.

{_GROUNDING}"""

_LEGAL = f"""\
You are a Regulatory Legal Analyst's assistant. Answer with a precise legal lens:
the exact rule/provision, its scope and definitions, and how it is worded. Quote
the relevant wording where it matters and avoid loose paraphrase.

{_GROUNDING}"""

# slug -> (display label, system prompt). 'general' reuses the standard RAG
# prompt so the default behaviour is unchanged.
_BUILTIN_ROLES: dict[str, tuple[str, str]] = {
    "general": ("General assistant", RAG_SYSTEM_PROMPT),
    "compliance-officer": ("Compliance Officer", _COMPLIANCE),
    "auditor": ("Internal Auditor", _AUDITOR),
    "legal": ("Legal Analyst", _LEGAL),
}


def role_prompt_name(slug: str) -> str:
    """Registry prompt name for a role slug: 'compliance-officer' -> 'role.compliance-officer'."""
    return f"{ROLE_PREFIX}{slug.strip().lower()}"


def role_slug_from_name(name: str) -> str | None:
    """Inverse of role_prompt_name; None if `name` isn't a role prompt."""
    return name[len(ROLE_PREFIX):] if name.startswith(ROLE_PREFIX) else None


def builtin_role_labels() -> dict[str, str]:
    """slug -> friendly label for the seeded roles (used to label the picker)."""
    return {slug: label for slug, (label, _tmpl) in _BUILTIN_ROLES.items()}


# Register each role as a gateway default so a DB version (curated via the
# Prompts UI) transparently overrides it — no redeploy needed.
for _slug, (_label, _template) in _BUILTIN_ROLES.items():
    register_default(role_prompt_name(_slug), _template)
