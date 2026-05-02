"""GET /v1/config — public runtime config the UI needs to render correctly."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from faastlab_askai_core.config import get_settings

router = APIRouter(tags=["config"])


class PublicConfig(BaseModel):
    name: str = "FaastLab AskAi"
    version: str = "0.1.0"
    default_tenant: str
    llm_model: str
    summarisation_model: str
    embeddings_model: str
    require_byok: bool
    reranker_provider: str


@router.get("/config", response_model=PublicConfig)
async def public_config() -> PublicConfig:
    s = get_settings()
    return PublicConfig(
        default_tenant=s.default_tenant,
        llm_model=s.llm_model,
        summarisation_model=s.summarisation_model,
        embeddings_model=s.embeddings_model,
        require_byok=s.require_byok,
        reranker_provider=s.reranker_provider,
    )
