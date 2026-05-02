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
