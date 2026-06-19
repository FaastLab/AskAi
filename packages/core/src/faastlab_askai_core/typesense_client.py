"""Typesense client + chunk-collection schema.

Typesense is a keyword + vector search engine with native hybrid ranking and
first-class facets. We use ONE shared collection (`chunks`) with a `tenant_id`
field; isolation between customers is enforced with scoped search API keys (the
key embeds a `tenant_id` filter Typesense applies server-side — see
`TypesenseRetriever`), the equivalent of our Postgres row-level-security
backstop. Postgres stays the system-of-record; Typesense is just an index.

The official `typesense` client is synchronous (requests-based). Our retrievers
are async, so callers wrap these calls in ``asyncio.to_thread`` to avoid
blocking the event loop.

Vectors are our OWN sovereign bge-m3 embeddings (bring-your-own) — we never use
Typesense's cloud embedders, to keep data on-prem.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

import typesense

from faastlab_askai_core.config import Settings, get_settings


def _node_from_url(url: str) -> dict[str, Any]:
    """Parse http(s)://host:port into a Typesense node dict."""
    parsed = urlparse(url)
    protocol = parsed.scheme or "http"
    host = parsed.hostname or "localhost"
    port = parsed.port or (443 if protocol == "https" else 8108)
    return {"host": host, "port": str(port), "protocol": protocol}


def get_typesense_client(settings: Settings | None = None) -> typesense.Client:
    """Build a Typesense client from settings. Raises if not configured."""
    s = settings or get_settings()
    if not s.typesense_url or not s.typesense_api_key:
        raise RuntimeError(
            "Typesense is not configured — set TYPESENSE_URL and TYPESENSE_API_KEY."
        )
    return typesense.Client(
        {
            "nodes": [_node_from_url(s.typesense_url)],
            "api_key": s.typesense_api_key,
            "connection_timeout_seconds": 5,
        }
    )


def chunk_schema(collection: str, embedding_dim: int) -> dict[str, Any]:
    """The `chunks` collection schema.

    Facetable fields (`tenant_id`, `doc_type`, `is_active`) power both filtering
    and the live facet counts in the search bar. `embedding` holds the bge-m3
    vector for the semantic half of hybrid search (cosine distance).
    """
    return {
        "name": collection,
        "enable_nested_fields": False,
        "fields": [
            # Identity / tenancy
            {"name": "tenant_id", "type": "string", "facet": True},
            {"name": "document_id", "type": "string", "facet": True},
            {"name": "chunk_id", "type": "string"},
            # Retrieval content + the keyword-searchable text
            {"name": "content", "type": "string"},
            {"name": "document_title", "type": "string", "optional": True},
            # Facets / filters (the show-off counts + doc-type filter)
            {"name": "doc_type", "type": "string", "facet": True, "optional": True},
            {"name": "is_active", "type": "bool", "facet": True},
            # Locator metadata (returned, not searched)
            {"name": "page_number", "type": "int32", "optional": True},
            {"name": "section_path", "type": "string", "optional": True},
            {"name": "effective_date", "type": "int64", "facet": True, "optional": True},
            # Sovereign bge-m3 vector for the semantic half of hybrid search.
            {"name": "embedding", "type": "float[]", "num_dim": embedding_dim},
        ],
        # Default sort by recency when relevance ties; optional field so it's safe
        # if absent.
        "default_sorting_field": None,
    }


def ensure_collection(
    client: typesense.Client, collection: str, embedding_dim: int
) -> None:
    """Create the chunks collection if it doesn't already exist (idempotent)."""
    try:
        client.collections[collection].retrieve()
        return  # already there
    except typesense.exceptions.ObjectNotFound:
        pass
    schema = chunk_schema(collection, embedding_dim)
    # Typesense rejects an explicit null default_sorting_field — drop it.
    schema = {k: v for k, v in schema.items() if v is not None}
    client.collections.create(schema)


def chunk_to_document(
    *,
    chunk_id: str,
    tenant_id: str,
    document_id: str,
    content: str,
    embedding: list[float],
    document_title: str | None = None,
    doc_type: str | None = None,
    is_active: bool = True,
    page_number: int | None = None,
    section_path: str | None = None,
    effective_date: int | None = None,
) -> dict[str, Any]:
    """Build a Typesense document for one chunk. `id` is the chunk id so writes
    are upserts (re-indexing a chunk overwrites, never duplicates)."""
    doc: dict[str, Any] = {
        "id": chunk_id,
        "chunk_id": chunk_id,
        "tenant_id": tenant_id,
        "document_id": document_id,
        "content": content,
        "is_active": is_active,
        "embedding": embedding,
    }
    if document_title is not None:
        doc["document_title"] = document_title
    if doc_type is not None:
        doc["doc_type"] = doc_type
    if page_number is not None:
        doc["page_number"] = page_number
    if section_path is not None:
        doc["section_path"] = section_path
    if effective_date is not None:
        doc["effective_date"] = effective_date
    return doc
