"""Observability — Langfuse tracing wrapper + Prometheus metrics shim.

Both are optional: enabled when their respective settings are present.
Application code calls `get_tracer()` and gets either a real Langfuse
client or a no-op tracer. Same idea for `get_metrics()`.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from functools import lru_cache
from typing import Any, Iterator, Protocol, runtime_checkable

from faastlab_askai_core.config import get_settings

log = logging.getLogger(__name__)


# ---- Tracer protocol -------------------------------------------------------


@runtime_checkable
class Tracer(Protocol):
    @contextmanager
    def trace(
        self, name: str, *, metadata: dict[str, Any] | None = None
    ) -> Iterator[None]: ...


class _NullTracer:
    @contextmanager
    def trace(
        self, name: str, *, metadata: dict[str, Any] | None = None
    ) -> Iterator[None]:
        yield


class _LangfuseTracer:
    def __init__(self, client: Any) -> None:
        self._client = client

    @contextmanager
    def trace(
        self, name: str, *, metadata: dict[str, Any] | None = None
    ) -> Iterator[None]:
        trace = self._client.trace(name=name, metadata=metadata or {})
        try:
            yield
        finally:
            try:
                trace.end()
            except Exception:  # noqa: BLE001
                pass


@lru_cache(maxsize=1)
def get_tracer() -> Tracer:
    settings = get_settings()
    if settings.observability_provider != "langfuse":
        return _NullTracer()
    if not (settings.langfuse_public_key and settings.langfuse_secret_key):
        log.warning("Langfuse keys missing — falling back to NullTracer")
        return _NullTracer()
    try:
        from langfuse import Langfuse  # type: ignore[import-not-found]
    except ImportError:
        log.warning("langfuse package not installed — install langfuse to enable")
        return _NullTracer()
    client = Langfuse(
        public_key=settings.langfuse_public_key,
        secret_key=settings.langfuse_secret_key,
        host=settings.langfuse_host,
    )
    return _LangfuseTracer(client)
