"""Reranker fine-tuning toolkit.

Train a domain-specific cross-encoder (e.g. UK FinReg) on top of
BAAI/bge-reranker-base. Earmarked as Oxford MSc dissertation work — the
output is a HuggingFace-publishable Apache-2.0 reranker that can drop
into AskAi by setting `BGE_RERANKER_MODEL=faastlab/finreg-reranker-v1`.

Modules:
- `triplets`  — generate (query, positive_chunk, negative_chunk) triples
                from your already-ingested corpus + an LLM "judge".
- `train`     — sentence-transformers cross-encoder fine-tune loop.
- `evaluate`  — precision@k / MRR / NDCG against a held-out query set.
"""

from faastlab_askai_search.training.triplets import (
    Triplet,
    generate_triplets,
)

__all__ = ["Triplet", "generate_triplets"]
