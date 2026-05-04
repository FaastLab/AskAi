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
    llm_provider: str
    llm_model: str
    summarisation_model: str
    embeddings_provider: str
    embeddings_model: str
    embeddings_dim: int
    require_byok: bool
    reranker_provider: str
    # `reranker_model` is only meaningful when reranker_provider == 'bge'
    # — the HuggingFace path of the cross-encoder loaded. Lets testers
    # confirm exactly which reranker is active during A/B comparisons.
    reranker_model: str | None = None


@router.get("/config", response_model=PublicConfig)
async def public_config() -> PublicConfig:
    s = get_settings()
    reranker_model: str | None = None
    if s.reranker_provider == "bge":
        reranker_model = s.bge_reranker_model
    elif s.reranker_provider == "cohere":
        reranker_model = "rerank-english-v3.0"  # what CohereReranker uses
    return PublicConfig(
        default_tenant=s.default_tenant,
        llm_provider=s.llm_provider,
        llm_model=s.llm_model,
        summarisation_model=s.summarisation_model,
        embeddings_provider=s.embeddings_provider,
        embeddings_model=s.embeddings_model,
        embeddings_dim=s.embeddings_dim,
        require_byok=s.require_byok,
        reranker_provider=s.reranker_provider,
        reranker_model=reranker_model,
    )
