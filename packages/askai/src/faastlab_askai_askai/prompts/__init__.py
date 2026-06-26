"""Prompts — system + few-shot templates for RAG."""

from faastlab_askai_askai.prompts.rag import (
    RAG_SYSTEM_PROMPT,
    REFUSAL_NO_CONTEXT,
    build_rag_messages,
)

# Import for its side effect: registers the built-in `role.*` prompts as gateway
# defaults so they're resolvable + show in the Prompts UI.
from faastlab_askai_askai.prompts.roles import (
    ROLE_PREFIX,
    builtin_role_labels,
    role_prompt_name,
    role_slug_from_name,
)

__all__ = [
    "RAG_SYSTEM_PROMPT",
    "REFUSAL_NO_CONTEXT",
    "ROLE_PREFIX",
    "build_rag_messages",
    "builtin_role_labels",
    "role_prompt_name",
    "role_slug_from_name",
]
