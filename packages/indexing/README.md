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
│   ├── xlsx.py                 # openpyxl, one block per row with headers
│   └── router.py               # detect_content_type + get_parser
├── chunkers/
│   ├── base.py                 # Chunker Protocol + Chunk dataclass
│   ├── recursive.py            # tiktoken-based RecursiveCharacterTextSplitter
│   ├── markdown.py             # heading-aware sectioning
│   ├── row.py                  # one chunk per spreadsheet row
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

## Excel workbooks (.xlsx / .xlsm)

Generic extractors flatten a workbook into one long text stream, so managed
indexers that cap extracted text per document (Azure AI Search: 4M chars on
higher tiers) silently drop the later rows, and size-based chunking splits
rows and separates values from their column headers.

`XlsxParser` emits one block per data row (`Sheet: X | Row N` followed by
`Header: value` lines; the first non-empty row is the header row, hidden
sheets are skipped) and the chunk router sends it to `RowChunker`, which
indexes one chunk per row and splits only very wide rows, repeating the
row label on each piece. Citations point at the exact sheet and row.

Measured on a synthetic 40,000-row register with BM25 retrieval
(`uv run python scripts/eval_xlsx_chunking.py`):

| strategy | recall@1 | recall@5 | MRR@10 |
|---|---|---|---|
| flattened, 4M-char cap, 1,000-char chunks | 1.5% | 8.5% | 0.053 |
| flattened, no cap, 1,000-char chunks | 1.0% | 11.0% | 0.059 |
| **row chunks (XlsxParser + RowChunker)** | **95.5%** | **100%** | **0.973** |

With the cap, 20% of rows never reach the index at all.

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
