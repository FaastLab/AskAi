"""Async SQLAlchemy engine and session factory."""

from __future__ import annotations

from functools import lru_cache

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from faastlab_askai_core.config import get_settings


@lru_cache(maxsize=1)
def get_engine() -> AsyncEngine:
    """Return the singleton async engine bound to `DATABASE_URL`."""
    settings = get_settings()
    return create_async_engine(
        settings.database_url,
        echo=settings.app_env == "dev" and settings.app_log_level == "DEBUG",
        pool_pre_ping=True,
        # Generous pool: audit middleware + sessions polling + retrieval +
        # memory writes can stack up under concurrent /v1/ask streams. A
        # connection-pool starve was the suspected cause of 10-15 min
        # browser stalls. Each connection is cheap; Postgres is fine with
        # 50+ idle connections.
        pool_size=20,
        max_overflow=40,
        pool_timeout=30,
        pool_recycle=1800,
    )


@lru_cache(maxsize=1)
def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    """Return the singleton session factory."""
    return async_sessionmaker(
        bind=get_engine(),
        expire_on_commit=False,
        class_=AsyncSession,
    )
