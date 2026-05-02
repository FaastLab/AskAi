# FaastLab AskAi

> **The open knowledge platform for humans and AI agents.**
> Ingest documents once. Query via chat, REST, MCP, or SDK. Deploy fully open-source, on Azure, on AWS, on-prem, or hybrid.

[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![FaastLab.Ai](https://img.shields.io/badge/by-FaastLab.Ai-purple.svg)](https://faastlab.ai)

---

## What is AskAi?

AskAi is FaastLab's flagship open-source platform for **document intelligence**. It does four things, all production-grade, all modular:

1. **Indexing** — ingest documents from any source, parse, chunk, embed
2. **Search & RAG** — hybrid retrieval (vector + keyword + metadata) with reranking
3. **Summarisation** — map-reduce summaries for documents of any length
4. **Ask AI** — chat over your documents, with citations and multi-step reasoning

It is designed to serve **three audiences from one codebase**:

- **Humans** — via a chat UI (Ask AI)
- **AI agents** — via REST, MCP server, or Python SDK (knowledge layer for agentic AI)
- **Validators** — agents that read documents and validate them against a corpus (e.g. regulatory report compliance)

---

## Why AskAi exists

Most open-source RAG projects are demos. Most enterprise knowledge platforms are SaaS-only or vendor-locked. There's a gap in the market for an **open, modular, agent-ready knowledge platform** that companies can:

- Self-host fully open-source
- Deploy on Azure / AWS / GCP using managed services
- Mix and match (e.g. OpenAI for LLM, Postgres for vectors, S3 for storage)

AskAi fills that gap. Every external dependency is behind an **adapter** — swap OpenAI for Azure OpenAI, swap Postgres for Azure AI Search, swap MinIO for S3 — without changing application code.

---

## Architecture at a glance

```
┌────────────────────────────────────────────────────────────────┐
│                    Interfaces (pick any/all)                    │
│   Chat UI (Next.js) │ REST API │ MCP Server │ Python SDK        │
└────────────────────────────────────────────────────────────────┘
                                │
┌────────────────────────────────────────────────────────────────┐
│                       Core Modules                              │
│  ┌──────────┐  ┌────────────┐  ┌──────────────┐  ┌──────────┐  │
│  │ Indexing │→ │ Search/RAG │→ │ Summarisation│→ │ Ask AI   │  │
│  └──────────┘  └────────────┘  └──────────────┘  └──────────┘  │
└────────────────────────────────────────────────────────────────┘
                                │
┌────────────────────────────────────────────────────────────────┐
│                    Adapter Layer (swappable)                    │
│  Storage │ Vector DB │ LLM │ Embeddings │ Queue │ Auth          │
└────────────────────────────────────────────────────────────────┘
                                │
┌────────────────────────────────────────────────────────────────┐
│       Default OSS stack (works out of the box)                  │
│  MinIO │ Postgres+pgvector │ OpenAI │ Redis+Celery │ JWT        │
│                                                                 │
│       Azure stack (one config change)                           │
│  Blob │ Azure AI Search │ Azure OpenAI │ Service Bus │ Entra    │
└────────────────────────────────────────────────────────────────┘
```

See [`ARCHITECTURE.md`](ARCHITECTURE.md) for the full design.

---

## Quick start

```bash
# Clone and enter
git clone https://github.com/faastlab-ai/askai.git
cd askai

# Set OpenAI key (or Azure OpenAI — see .env.example)
cp .env.example .env

# Spin up everything
docker compose up -d

# Ingest a sample corpus (UK Financial Regulation)
make demo-corpus

# Open the chat UI
open http://localhost:3000
```

That's it. You now have a working knowledge platform with chat, REST API, and MCP server — all running locally, no cloud account needed.

---

## Use cases

**For companies wanting chat over docs**
Drop in your SharePoint, Confluence, or S3 documents. Get a chat UI for your team.

**For companies building AI agents**
Use AskAi as the knowledge backbone. Any agent (Claude, LangGraph, CrewAI, custom) can call it via REST or MCP.

**For regulatory / compliance use**
Ingest regulations and standards. Build validator agents that check reports, contracts, or designs against the corpus, with full paragraph-level citations.

**For consultancies (like FaastLab)**
Deliver document intelligence to clients on whatever stack they have — fully open, fully Azure, or anything in between.

---

## Deployment options

| Mode | Storage | Vector DB | LLM | Use case |
|------|---------|-----------|-----|----------|
| **Pure OSS** | MinIO | Postgres+pgvector | OpenAI / local LLM | Self-host, no cloud lock-in |
| **Azure** | Blob | Azure AI Search | Azure OpenAI | Enterprise on Azure |
| **AWS** | S3 | OpenSearch / pgvector on RDS | Bedrock / OpenAI | Enterprise on AWS |
| **Hybrid** | S3 + Postgres on-prem | pgvector | Azure OpenAI | Mixed regulated environments |

All controlled by config. No code changes between modes.

---

## Project status

Active development. See [`ARCHITECTURE.md`](ARCHITECTURE.md) and [`CLAUDE.md`](CLAUDE.md) for the full design and build plan.

---

## License

Apache License 2.0 — free for any use, commercial or otherwise, with an explicit patent grant. Built and maintained by [FaastLab.Ai](https://faastlab.ai).