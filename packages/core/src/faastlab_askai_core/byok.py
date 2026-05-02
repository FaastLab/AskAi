"""Bring-your-own-key (BYOK) adapter override.

For public live demos: the request can supply its own OpenAI / Cohere
API key via headers, and the API will build per-request adapter
instances using that key — leaving the server's `OPENAI_API_KEY` for
system tasks only (or unset entirely for a true OSS demo).

The header → adapter wiring lives in `packages/api/middleware/byok.py`;
this module just exposes `RequestSecrets` and a small factory hook the
API depends on.
"""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass


@dataclass(slots=True, frozen=True)
class RequestSecrets:
    """Per-request credential overrides supplied by the caller."""

    openai_api_key: str | None = None
    cohere_api_key: str | None = None

    @property
    def has_any(self) -> bool:
        return bool(self.openai_api_key or self.cohere_api_key)


# Context-var so the request-bound secrets are visible to lazily-built
# adapters without threading them through every call site.
_current: ContextVar[RequestSecrets | None] = ContextVar(
    "askai_request_secrets", default=None
)


def set_request_secrets(secrets: RequestSecrets | None) -> object:
    """Set request-scoped secrets; returns a token to reset later."""
    return _current.set(secrets)


def reset_request_secrets(token: object) -> None:
    """Reset to the previous value (use the token from set_request_secrets)."""
    _current.reset(token)  # type: ignore[arg-type]


def get_request_secrets() -> RequestSecrets | None:
    """Return the secrets bound to the current request, if any."""
    return _current.get()
