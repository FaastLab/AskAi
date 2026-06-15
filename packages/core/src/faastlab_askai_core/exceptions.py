"""Exception hierarchy for AskAi.

All exceptions raised by AskAi packages must subclass `AskAiError` so
callers can catch the whole tree without depending on individual modules.
"""

from __future__ import annotations


class AskAiError(Exception):
    """Base exception for all AskAi errors."""


# ---- Configuration ----------------------------------------------------------


class ConfigurationError(AskAiError):
    """Raised when settings or factory wiring is invalid."""


class AdapterNotFoundError(ConfigurationError):
    """Requested adapter implementation is not registered."""


# ---- Tenancy & auth ---------------------------------------------------------


class TenantError(AskAiError):
    """Base class for tenant-related failures."""


class TenantNotFoundError(TenantError):
    """No tenant matches the supplied id or slug."""


class CrossTenantAccessError(TenantError):
    """An attempt was made to access data outside the caller's tenant."""


class AuthenticationError(AskAiError):
    """Caller could not be authenticated."""


class AuthorizationError(AskAiError):
    """Caller is authenticated but not allowed to perform this action."""


# ---- Indexing ---------------------------------------------------------------


class IndexingError(AskAiError):
    """Base class for indexing failures."""


class ParserError(IndexingError):
    """A parser failed to extract content from a document."""


class EmbeddingError(IndexingError):
    """An embedding call failed."""


# ---- Search & retrieval -----------------------------------------------------


class SearchError(AskAiError):
    """Base class for search failures."""


class RerankerError(SearchError):
    """A reranker call failed."""


# ---- LLM / Ask AI -----------------------------------------------------------


class LLMError(AskAiError):
    """Base class for LLM-related failures."""


class LLMTimeoutError(LLMError):
    """LLM call exceeded the configured timeout."""


class LLMRateLimitError(LLMError):
    """LLM provider returned a rate-limit error."""


# ---- AI Gateway -------------------------------------------------------------


class GatewayError(AskAiError):
    """Base class for AI-gateway failures."""


class PolicyViolation(GatewayError):
    """A request is disallowed by the tenant's governance policy (suspended
    AI, model not on the allow-list, etc.). The API maps this to HTTP 403."""


class GuardViolation(PolicyViolation):
    """The prompt was blocked by a safety guard (e.g. jailbreak / prompt-
    injection detection) before reaching the model. Subclasses PolicyViolation
    so the API maps it to HTTP 403 via the same handler."""


class PromptNotFoundError(GatewayError):
    """No prompt matches the requested name (and version)."""


class PromptRenderError(GatewayError):
    """A prompt template could not be rendered (missing variable)."""


class QuotaExceeded(GatewayError):
    """A tenant has exhausted its per-tenant request or token quota.

    Carries the limit/usage that tripped so callers (the API layer) can
    surface a precise 429 with remaining-quota headers.
    """

    def __init__(
        self,
        message: str,
        *,
        limit_kind: str,
        limit: int,
        used: int,
    ) -> None:
        super().__init__(message)
        self.limit_kind = limit_kind  # "requests" | "tokens"
        self.limit = limit
        self.used = used
