# `faastlab-askai-search`

Phase 3 — implemented.

## What lives here

```
src/faastlab_askai_search/
├── filters.py                 # SearchFilters dataclass (doc_type, dates, only_active, …)
├── retrievers/
│   ├── base.py                # Retriever Protocol + RetrievedChunk dataclass
│   ├── vector.py              # pgvector ANN (HNSW, cosine)
│   ├── keyword.py             # Postgres tsvector BM25-equivalent
│   └── hybrid.py              # RRF fusion (k_const=60, parallel calls)
├── rerankers/
│   ├── base.py                # Reranker Protocol
│   ├── noop.py                # pass-through (default)
│   ├── cohere_reranker.py     # Cohere Rerank (rerank-english-v3.0)
│   └── bge.py                 # BAAI/bge-reranker-* via sentence-transformers
├── service.py                 # SearchService — filter → retrieve → rerank → score
└── cli.py                     # `python -m faastlab_askai_search.cli`
```

## Defaults

- **Retriever**: `HybridRetriever` (vector + keyword + RRF)
- **Reranker**: `NoOpReranker` (no API key required out of the box)
- **`only_active=True`**: superseded regulatory docs are excluded by default
  (set in `SearchFilters` and detected at ingestion via the supersession
  heuristic in `faastlab_askai_indexing.supersession`)

## Switching reranker

Cohere (recommended for quality, free tier ~1000/month):
```bash
# in .env
RERANKER_PROVIDER=cohere
COHERE_API_KEY=...
```

Local bge-reranker (free, ~500MB model, slower):
```bash
uv pip install -e 'packages/search[bge-reranker]'
# in .env
RERANKER_PROVIDER=bge
BGE_RERANKER_MODEL=BAAI/bge-reranker-large
```

## Running a search

```bash
# Ingest first (Phase 2)
make ingest TENANT=demo-public SOURCE=./corpus/uk_finreg/_downloads

# Then query
make search TENANT=demo-public QUERY="What does the PRA say about EU withdrawal?"

# Include superseded documents
uv run python -m faastlab_askai_search.cli \
  --tenant demo-public \
  --query "EU withdrawal" \
  --include-superseded
```
