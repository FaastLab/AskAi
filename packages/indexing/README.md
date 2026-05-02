# `faastlab-askai-indexing`

Phase 2 — implemented.

## What lives here

```
src/faastlab_askai_indexing/
├── adapters/
│   ├── embeddings_openai.py    # EmbeddingsAdapter (OpenAI / Azure OpenAI)
│   ├── storage_minio.py        # StorageAdapter (MinIO / S3-compatible)
│   └── vector_pgvector.py      # VectorStoreAdapter (Postgres + pgvector)
├── parsers/
│   ├── base.py                 # Parser Protocol + ParsedBlock dataclass
│   ├── pdf.py                  # PyMuPDF (default; Unstructured fallback planned)
│   ├── docx.py                 # python-docx
│   ├── html.py                 # BeautifulSoup, drops nav/footer/script
│   ├── markdown.py             # ATX heading-aware
│   └── router.py               # detect_content_type + get_parser
├── chunkers/
│   ├── base.py                 # Chunker Protocol + Chunk dataclass
│   ├── recursive.py            # tiktoken-based RecursiveCharacterTextSplitter
│   ├── markdown.py             # heading-aware sectioning
│   └── router.py               # picks chunker from parser metadata
├── connectors/
│   ├── base.py                 # Connector Protocol + SourceDocument
│   ├── filesystem.py           # walk a local directory
│   └── s3.py                   # iterate S3-compatible bucket
├── hashing.py                  # SHA-256 content hash for idempotency
├── pipeline.py                 # connector → parse → chunk → embed → store
├── celery_app.py               # Celery app (broker = Redis)
├── tasks.py                    # ingest_filesystem / ingest_s3 tasks
└── cli.py                      # `python -m faastlab_askai_indexing.cli`
```

## Running an ingestion

Local demo (drop PDFs into `corpus/uk_finreg/_downloads/`):

```bash
# from repo root
make up                                          # postgres + redis + minio
make migrate                                     # if not already done
mkdir -p corpus/uk_finreg/_downloads
# put a BoE/FCA PDF in there
make ingest TENANT=demo-public PATH=./corpus/uk_finreg/_downloads
```

Or via Celery (in two terminals):

```bash
# terminal 1
make worker

# terminal 2 — enqueue
uv run python -c "
from faastlab_askai_indexing.tasks import ingest_filesystem
result = ingest_filesystem.delay('demo-public-tenant-uuid', './corpus/uk_finreg/_downloads')
print(result.get(timeout=600))
"
```

## Idempotency

The pipeline hashes each document's bytes (SHA-256) and stores the digest
in `documents.content_hash`. On re-ingestion:

- Same `(tenant_id, source_uri, content_hash)` → skipped (no work).
- Same source_uri but new hash → existing chunks deleted, doc re-indexed
  in place (`document_id` preserved so external references still work).
- Brand new source_uri → fresh document + chunks.

## Tests

```bash
make test                # unit tests for parsers, chunkers, hashing
```

End-to-end ingestion has its own integration smoke test under
`tests/integration/` (requires a running stack — covered by Phase 2.5).
