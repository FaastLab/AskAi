"""BYOK middleware — bind per-request API keys from headers.

Visitors to a public demo can supply their own OpenAI / Cohere keys in
HTTP headers (so they pay for their own usage). The keys are bound to
a `contextvars` slot for the duration of the request, then cleared.

Headers honoured:
  X-OpenAI-API-Key
  X-Cohere-API-Key

Aliases also accepted (some browsers/SDKs prefer lowercase variants):
  X-Api-Key-Openai, X-Api-Key-Cohere
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from starlette.middleware.base import BaseHTTPMiddleware

from faastlab_askai_core.byok import (
    RequestSecrets,
    reset_request_secrets,
    set_request_secrets,
)

if TYPE_CHECKING:
    from starlette.requests import Request
    from starlette.responses import Response
    from starlette.types import ASGIApp


_OPENAI_HEADERS = ("x-openai-api-key", "x-api-key-openai")
_COHERE_HEADERS = ("x-cohere-api-key", "x-api-key-cohere")


def _pick(headers, names: tuple[str, ...]) -> str | None:
    for name in names:
        value = headers.get(name)
        if value:
            stripped = value.strip()
            if stripped:
                return stripped
    return None


class BYOKMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: "Request", call_next):  # type: ignore[no-untyped-def]
        secrets = RequestSecrets(
            openai_api_key=_pick(request.headers, _OPENAI_HEADERS),
            cohere_api_key=_pick(request.headers, _COHERE_HEADERS),
        )
        if secrets.has_any:
            request.state.byok = secrets
            token = set_request_secrets(secrets)
        else:
            token = None

        try:
            response: Response = await call_next(request)
            return response
        finally:
            if token is not None:
                reset_request_secrets(token)
