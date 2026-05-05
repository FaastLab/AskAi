# AskAi — Architecture

> Full technical design for FaastLab AskAi.
> Companion to `README.md` (vision and quick-start).

---

## 1. Goals & non-goals

### Goals
- One codebase serving humans (chat), agents (MCP/REST/SDK), and validators (compliance agents)
- Modular monorepo — every external dependency behind an adapter
- Pure-OSS default stack, with first-class Azure and AWS support via config
- Multi-tenant from day one (internal use, demo, client deployments coexist)
- Paragraph-level citations, version awareness, structured retrieval
- Production-ready: observability, audit logging, auth, rate limiting

### Non-goals
- Not a document editor or CMS
- Not a fine-tuning platform — uses base LLMs via API
- Not trying to replace Glean/Guru — open-source, self-hostable, agent-first

---

## 2. The four core modules

### 2.1 Indexing
Pulls documents from sources, parses them, chunks them, embeds them, stores them.

**Responsibilities:**
- Connectors: filesystem, S3/MinIO/Blob, SharePoint, Confluence, web URLs
- Parsing: PDF (PyMuPDF + Unstructured fallback), DOCX, HTML, Markdown, OCR for scanned
- Chunking: structure-aware (`MarkdownHeaderTextSplitter` for MD, `RecursiveCharacterTextSplitter` otherwise), 500–800 tokens, 10–15% overlap
- Embedding: pluggable (OpenAI `text-embedding-3-large` default; bge-large for self-hosted)
- Metadata extraction: title, author, date, version, custom tags, keyphrases
- Idempotency: re-ingesting the same doc updates rather than duplicates
- Async: Celery tasks, queue per tenant, per-doc state machine

### 2.2 Search & RAG
Hybrid retrieval over the indexed corpus.

**Responsibilities:**
- Vector search (pgvector HNSW)
- Keyword search (Postgres `tsvector` BM25-equivalent)
- Reciprocal Rank Fusion to combine
- Reranker (Cohere Rerank or `bge-reranker` self-hosted)
- Metadata filters (tenant, date, doc type, custom fields)
- Confidence scoring on results
- Returns structured chunks with paragraph-level location

### 2.3 Summarisation
Pre-computes per-document summaries; supports on-demand summary too.

**Responsibilities:**
- Map-reduce pipeline for long documents (handles 200+ page PDFs)
- Map phase: chunk-level mini-summaries
- Reduce phase: combine into coherent doc summary
- Optional focus mode: summary biased toward a query/topic
- Stores summary in `documents.summary` column for fast retrieval
- Re-runs only when source doc changes

### 2.4 Ask AI
Chat layer with multi-step agentic reasoning.

**Responsibilities:**
- Query rewriting for follow-ups (history-aware retrieval)
- Single-shot RAG (default, fast path)
- Multi-step agentic flow (LangGraph) for complex questions:
  - Comparison: "compare X policy vs Y policy"
  - Multi-hop: "who approved the rule that governs X?"
  - Time-aware: "how has X changed since 2022?"
- Streaming responses (SSE)
- Inline citations linked to source chunks
- Session memory in Postgres

---

## 3. Interfaces

AskAi exposes the same core capability through four interfaces:

### REST API
Primary surface. OpenAPI/Swagger documented. Used by chat UI and any custom integration.

Key endpoints:
- `POST /v1/ingest` — kick off ingestion
- `POST /v1/search` — hybrid search returning chunks
- `POST /v1/ask` — full RAG answer (streaming)
- `GET /v1/documents/{id}` — full doc retrieval
- `GET /v1/documents/{id}/summary` — pre-computed summary
- `POST /v1/compare` — multi-doc comparison
- `GET /v1/documents/{id}/history` — version history

### MCP Server
[Model Context Protocol](https://modelcontextprotocol.io/) server exposing the REST capabilities as tools. Any MCP-compatible agent (Claude Desktop, Cursor, custom LangGraph agents) can plug in instantly.

Tools exposed:
- `search_documents`
- `get_document`
- `get_summary`
- `compare_documents`
- `find_similar`
- `list_recent`
- `get_section` (paragraph-level)

### Python SDK
Thin wrapper over REST. For LangChain/LangGraph/CrewAI direct use.

```python
from faastlab_askai import AskAiClient
client = AskAiClient(base_url=..., api_key=...)
chunks = client.search("capital requirements for UK banks")
answer = client.ask("Summarise FCA's stance on consumer duty", stream=True)
```

### Chat UI
Next.js + Tailwind + SSE streaming. Split-pane: answer on left, sources on right with click-to-open.

---

## 4. Adapter pattern

Every external dependency is behind a Python protocol. Implementations are picked at startup from config.

```python
# Storage adapter
class StorageAdapter(Protocol):
    async def get(self, key: str) -> bytes: ...
    async def put(self, key: str, data: bytes) -> None: ...

# Implementations
class MinIOStorage(StorageAdapter): ...
class S3Storage(StorageAdapter): ...
class AzureBlobStorage(StorageAdapter): ...
```

Same pattern for:
- **VectorStore** — pgvector / Qdrant / Azure AI Search / Pinecone
- **LLM** — OpenAI / Azure OpenAI / Anthropic / Bedrock / Ollama
- **Embeddings** — OpenAI / Cohere / HuggingFace / Azure OpenAI
- **Queue** — Celery+Redis / Azure Service Bus / SQS
- **Auth** — JWT / OIDC / Entra / Auth0

Switching is a config change, not a code change.

---

## 5. Data model (Postgres)

Single Postgres instance handles everything early on. Split out as scale requires.

**Core tables:**
- `tenants` — multi-tenant isolation
- `documents` — primary index: id, tenant_id, title, source_url, doc_type, version, effective_date, superseded_by, metadata (JSONB), keyphrases, summary
- `document_versions` — version history for change tracking
- `chunks` — id, document_id, tenant_id, content, embedding (vector), section_path, page_number, char_start, char_end, tsv (tsvector for keyword search)
- `ingestion_jobs` — async job state per document
- `chat_sessions` — user_id, tenant_id, history, created_at
- `audit_log` — every retrieval and answer, with user, query, sources returned

**Key indexes:**
- HNSW on `chunks.embedding` for vector search
- GIN on `chunks.tsv` for full-text search
- B-tree on `documents.tenant_id`, `documents.effective_date`
- Composite on `(tenant_id, doc_type)` for filtered retrieval

---

## 6. Multi-tenancy

`tenant_id` is on every table, every API call, every search filter, every queue. Three default tenants shipped:

- `demo-public` — UK Financial Regulation corpus (BoE, FCA, PRA)
- `demo-template` — empty template clients can clone for their own tenant

Auth middleware injects `tenant_id` from JWT claims. No cross-tenant access ever.

---

## 7. Agentic capability

AskAi is designed as a knowledge layer **for** agents, not as a competing agent platform. But it ships with one reference agent module (`validators/`) showing how to build agents on top.

### Reference: regulatory report validator
Takes a regulatory report (PDF), parses the claims it makes, queries
AskAi for the matching rules in your indexed regulatory corpus,
compares, and produces a traffic-light verdict with paragraph-level
citations — exactly the workflow a fintech compliance officer or a
PRA / FCA submission reviewer needs.

---

## 8. Observability

- **LangSmith or Langfuse** — LLM call tracing, prompt versioning, eval runs
- **Prometheus + Grafana** — infra metrics
- **Sentry** — error tracking
- **Audit log table** — every query, every retrieval, every answer, with full provenance for compliance use cases

---

## 9. Security

- TLS everywhere
- Secrets via env / Azure Key Vault / AWS Secrets Manager (adapter)
- Tenant isolation enforced at DB query level (row-level security in Postgres)
- Rate limiting per API key
- PII scrubbing option on ingestion (configurable)
- Optional response-time guardrails (content filter agent before output)

---

## 10. Deployment

- **Dev:** `docker compose up` — Postgres, Redis, MinIO, API, Worker, UI
- **Prod (OSS):** Kubernetes with Helm chart
- **Prod (Azure):** ARM/Bicep templates for AKS + managed services
- **Prod (AWS):** Terraform for ECS/EKS + RDS + S3
- **CI/CD:** GitHub Actions — lint, type-check, test, build, deploy

---

## 11. Tech stack

| Layer | Default | Azure swap | AWS swap |
|-------|---------|-----------|----------|
| Language | Python 3.12 | same | same |
| Backend | FastAPI | same | same |
| Frontend | Next.js 14 + Tailwind | same | same |
| Vector DB | pgvector (HNSW) | Azure AI Search | OpenSearch / pgvector on RDS |
| Database | Postgres 16 | Azure DB for Postgres | RDS Postgres |
| Storage | MinIO | Azure Blob | S3 |
| Queue | Celery + Redis | Service Bus | SQS |
| LLM | OpenAI GPT-4o | Azure OpenAI | Bedrock / OpenAI |
| Embeddings | OpenAI text-embedding-3-large | Azure OpenAI | same |
| Reranker | Cohere Rerank or bge-reranker | same | same |
| Orchestration | LangChain + LangGraph | same | same |
| Observability | Langfuse / LangSmith | same | same |
| Auth | JWT (default), OIDC | Entra ID | Cognito |
| Container | Docker | same | same |
| Orchestrator | Kubernetes (Helm) | AKS | EKS / ECS |

---

## 12. Repository layout

```
AskAi/
├── README.md
├── Architecture.md
├── LICENSE
├── docker-compose.yml
├── .env.example
├── Makefile
├── pyproject.toml                  # Python workspace root
│
├── packages/
│   ├── core/                       # Shared: models, adapters, config
│   │   ├── adapters/               # Storage, vector, LLM, queue, auth
│   │   ├── db/                     # SQLAlchemy models, Alembic migrations
│   │   ├── schemas/                # Pydantic schemas
│   │   └── config/                 # Pydantic Settings
│   │
│   ├── indexing/                   # Module 1
│   │   ├── connectors/             # Filesystem, S3, SharePoint, web
│   │   ├── parsers/                # PDF, DOCX, HTML, OCR
│   │   ├── chunkers/
│   │   ├── embedders/
│   │   ├── pipeline.py             # Orchestrates ingestion
│   │   └── tasks.py                # Celery tasks
│   │
│   ├── search/                     # Module 2
│   │   ├── vector.py               # pgvector retriever
│   │   ├── keyword.py              # tsvector retriever
│   │   ├── hybrid.py               # RRF fusion
│   │   ├── reranker.py
│   │   └── filters.py
│   │
│   ├── summarisation/              # Module 3
│   │   ├── map_reduce.py
│   │   ├── focused.py              # Query-biased summary
│   │   └── tasks.py                # Celery tasks
│   │
│   ├── askai/                      # Module 4
│   │   ├── chains/                 # LangChain RAG chain
│   │   ├── graphs/                 # LangGraph multi-step flows
│   │   ├── prompts/
│   │   └── memory.py
│   │
│   ├── api/                        # FastAPI app
│   │   ├── routes/
│   │   ├── middleware/
│   │   ├── streaming.py
│   │   └── main.py
│   │
│   ├── mcp/                        # MCP server
│   │   ├── tools/
│   │   └── server.py
│   │
│   ├── sdk/                        # Python SDK
│   │   └── client.py
│   │
│   └── validators/                 # Reference agent: regulatory validator
│       ├── pipeline.py
│       └── prompts/
│
├── apps/
│   └── web/                        # Next.js chat UI
│       ├── app/
│       ├── components/
│       └── lib/
│
├── corpus/                         # Demo corpus loaders
│   └── uk_finreg/                  # BoE + FCA + PRA loader
│
├── tests/
│   ├── unit/
│   ├── integration/
│   └── eval/                       # RAG eval harness with golden Q&A
│
└── infra/
    ├── helm/
    ├── azure/                      # Bicep
    ├── aws/                        # Terraform
    └── github-actions/
```

---

## 13. Key design decisions & rationale

| Decision | Why |
|---|---|
| Monorepo | Shared DB models, adapters, config — splitting would mean publishing internal packages |
| Postgres + pgvector default | One DB for vectors, metadata, sessions, audit. HNSW handles 1–10M vectors easily |
| Adapter pattern everywhere | The whole point — clients pick OSS / cloud / hybrid without code changes |
| LangChain + LangGraph | Production-ready, fast iteration, huge ecosystem. Pin versions, add tracing |
| MCP as first-class | Agentic AI is the bigger market than chat. MCP is becoming the standard |
| Multi-tenant from day one | Internal + demo + clients coexist. Retrofitting is painful |
| Paragraph-level citations | Required for validator use cases. Cheap to add now, expensive later |
| Pre-computed summaries | Quality over latency. Re-run only on doc change |
| Reference validator agent | Shows the platform's ceiling in 50 lines of code |

---

## 14. Open questions / future work

- Real-time ingestion via webhooks (SharePoint change notifications, S3 events)
- GraphRAG layer for cross-document entity reasoning
- Fine-grained ACLs (document-level permissions, not just tenant)
- Multi-modal: image + chart retrieval (e.g. for tables and diagrams in regulatory PDFs)
- Local LLM support out of the box (Ollama adapter) for fully air-gapped deployments