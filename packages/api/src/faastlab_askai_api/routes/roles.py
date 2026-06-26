"""Assistant roles — list selectable roles + manage the tenant default.

A role is a registry prompt named ``role.<slug>`` (built-ins seeded in
``faastlab_askai_askai.prompts.roles``; customers add more via the Prompts UI by
creating a prompt named ``role.*``). The chat UI lists these and sends a role per
question; the tenant default applies when the user doesn't pick one.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select

from faastlab_askai_api.audit_helper import record_action
from faastlab_askai_api.middleware.principal import get_principal, require_scope
from faastlab_askai_askai.prompts import builtin_role_labels, role_slug_from_name
from faastlab_askai_core.adapters import Principal
from faastlab_askai_core.db import Tenant, get_sessionmaker
from faastlab_askai_core.gateway import PromptRegistry

router = APIRouter(tags=["roles"], prefix="/roles")
_prompts = PromptRegistry()


class Role(BaseModel):
    slug: str
    label: str


class RolesResponse(BaseModel):
    roles: list[Role]
    default_role: str | None  # tenant default slug, or None


class DefaultRoleUpdate(BaseModel):
    role: str | None = None  # slug, or null to clear the default


async def _tenant_default_role(tenant_id) -> str | None:
    sm = get_sessionmaker()
    async with sm() as session:
        settings = (
            await session.execute(
                select(Tenant.settings).where(Tenant.id == tenant_id)
            )
        ).scalar_one_or_none()
    role = (settings or {}).get("default_role")
    return role if isinstance(role, str) and role.strip() else None


async def _all_roles() -> list[Role]:
    """Built-in roles plus any custom ``role.*`` prompts from the registry."""
    labels: dict[str, str] = dict(builtin_role_labels())
    try:
        for summary in await _prompts.list_all():
            slug = role_slug_from_name(summary.name)
            if slug and slug not in labels:
                # Humanise an unknown slug for its picker label.
                labels[slug] = slug.replace("-", " ").replace("_", " ").title()
    except Exception:
        pass
    return [Role(slug=s, label=lbl) for s, lbl in sorted(labels.items())]


@router.get("", response_model=RolesResponse)
async def list_roles(
    principal: Principal = Depends(get_principal),
) -> RolesResponse:
    """Selectable roles + the tenant's current default (any member)."""
    return RolesResponse(
        roles=await _all_roles(),
        default_role=await _tenant_default_role(principal.tenant_id),
    )


@router.put("/default", response_model=RolesResponse)
async def set_default_role(
    body: DefaultRoleUpdate,
    principal: Principal = Depends(require_scope("owner")),
) -> RolesResponse:
    """Set/clear the tenant default role (owner-only). Stored in
    ``tenant.settings['default_role']`` (JSONB; no migration)."""
    slug = (body.role or "").strip() or None
    sm = get_sessionmaker()
    async with sm() as session:
        tenant = await session.get(Tenant, principal.tenant_id)
        if tenant is not None:
            settings = dict(tenant.settings or {})
            if slug:
                settings["default_role"] = slug
            else:
                settings.pop("default_role", None)
            tenant.settings = settings  # reassign so JSONB is flagged dirty
            await session.commit()
    await record_action(
        principal=principal,
        action="roles.set_default",
        resource="/v1/roles/default",
        extra={"role": slug},
    )
    return RolesResponse(roles=await _all_roles(), default_role=slug)
