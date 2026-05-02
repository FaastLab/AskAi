"""Tenant listing — read-only, scoped to the caller's tenant."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select

from faastlab_askai_core.adapters import Principal
from faastlab_askai_core.db import Tenant, get_sessionmaker
from faastlab_askai_core.schemas.tenant import TenantRead

from faastlab_askai_api.middleware.principal import get_principal

router = APIRouter(tags=["tenants"])


@router.get("/tenants/me", response_model=TenantRead)
async def get_my_tenant(principal: Principal = Depends(get_principal)) -> TenantRead:
    sm = get_sessionmaker()
    async with sm() as session:
        result = await session.execute(
            select(Tenant).where(Tenant.id == principal.tenant_id)
        )
        tenant = result.scalar_one()
    return TenantRead.model_validate(tenant)
