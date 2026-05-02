"""FastAPI app factory and entry-point.

Usage (dev):
    uvicorn faastlab_askai_api.main:app --reload --host 0.0.0.0 --port 8000

The app is split into route modules under `faastlab_askai_api.routes`
and middleware under `faastlab_askai_api.middleware`. Endpoints follow
`ARCHITECTURE.md` §3 closely.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from faastlab_askai_core.config import get_settings

from faastlab_askai_api.middleware.audit import AuditMiddleware
from faastlab_askai_api.middleware.byok import BYOKMiddleware
from faastlab_askai_api.middleware.principal import (
    rate_limit_key,
)
from faastlab_askai_api.routes import (
    ask,
    config as config_route,
    documents,
    health,
    ingest,
    search,
    sessions,
    tenants,
)


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Pre-warm the LLM/embeddings adapters so the first request isn't
    # slow with model downloads (especially bge-reranker).
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    limiter = Limiter(key_func=rate_limit_key)

    app = FastAPI(
        title="FaastLab AskAi",
        version="0.1.0",
        description="Open knowledge platform for humans and AI agents.",
        lifespan=_lifespan,
    )

    # ---- Middleware ----
    app.state.limiter = limiter
    app.add_middleware(SlowAPIMiddleware)
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-OpenAI-API-Key", "X-Cohere-API-Key"],
    )
    app.add_middleware(BYOKMiddleware)
    app.add_middleware(AuditMiddleware)

    # ---- Routes ----
    app.include_router(health.router)
    app.include_router(config_route.router, prefix="/v1")
    app.include_router(tenants.router, prefix="/v1")
    app.include_router(documents.router, prefix="/v1")
    app.include_router(ingest.router, prefix="/v1")
    app.include_router(search.router, prefix="/v1")
    app.include_router(ask.router, prefix="/v1")
    app.include_router(sessions.router, prefix="/v1")

    return app


app = create_app()
