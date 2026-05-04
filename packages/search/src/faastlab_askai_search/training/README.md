# Reranker fine-tuning toolkit

Train a domain-specific cross-encoder on top of `BAAI/bge-reranker-base`
and plug it into AskAi by changing one env var. The toolkit is
deliberately small and well-commented because it doubles as the code
artifact for an Oxford MSc dissertation.

## Pipeline

```
ingested chunks → triplets.py → triplets.jsonl → train.py → finreg-reranker-v1/
                                                              ↓
                                                    BGE_RERANKER_MODEL=/abs/path
                                                              ↓
                                                  evaluate.py → metrics table
```

## 1. Generate triplets

Sample N chunks from your already-ingested corpus, ask the LLM to
write 1–3 plausible questions per chunk (synthetic queries), pair
each with the source chunk (positive) and a different chunk from the
**same document** (hard negative).

```bash
make rerank-triplets TENANT=demo-public SAMPLE=500
# → training/triplets.jsonl
```

You'll want at least 500–1000 triplets; the FCA + BoE corpus the
demo loader pulls in supports a few thousand comfortably.

## 2. Fine-tune

Runs on CPU (slow) or any CUDA GPU (3090 fits the base model
comfortably). ~30 minutes for 3 epochs of 5k triplets on a 3090.

```bash
make rerank-train OUT=training/finreg-reranker-v1
# → training/finreg-reranker-v1/   (HuggingFace-format dir)
# → training/finreg-reranker-v1/train_log.json  (config + final metrics)
```

## 3. Evaluate vs baselines

Hand-curate a held-out query set (`training/eval_queries.jsonl` —
one JSON per line: `{"query": "...", "relevant_chunk_ids": [...]}`).
The evaluator runs the same questions through each reranker and
prints a table:

```bash
make rerank-eval TENANT=demo-public \
  RERANKERS="none bge cohere training/finreg-reranker-v1"
```

Output:
```
Reranker                              MRR@10  NDCG@10   R@5  R@10     ms
--------------------------------------------------------------------------------
none                                   0.412    0.490  0.420 0.640    180
bge                                    0.601    0.668  0.620 0.760   3200
cohere                                 0.643    0.700  0.650 0.780    250
training/finreg-reranker-v1            0.711    0.762  0.700 0.820    220
```

## 4. Plug into AskAi

```env
RERANKER_PROVIDER=bge
BGE_RERANKER_MODEL=/abs/path/to/training/finreg-reranker-v1
# Or after publishing to HuggingFace:
# BGE_RERANKER_MODEL=faastlab/finreg-reranker-v1
```

Restart the api: `docker compose --profile app restart api worker`.

The `/v1/config` endpoint will report your new model:
```json
{
  "reranker_provider": "bge",
  "reranker_model": "faastlab/finreg-reranker-v1"
}
```

## Hyper-parameter defaults (override on CLI)

| Param | Default | Notes |
|---|---|---|
| `--base-model` | `BAAI/bge-reranker-base` | ~280 MB, fits any laptop GPU |
| `--epochs` | 3 | More overfits on small datasets |
| `--batch-size` | 16 | Bump to 32–64 if you have VRAM |
| `--learning-rate` | 2e-5 | Standard for cross-encoder fine-tune |
| `--eval-split` | 0.10 | 10% held out for pairwise accuracy check |
| `--seed` | 42 | Reproducible |

## Citing in a thesis

Each trained model directory contains `train_log.json` with:
- triplets file path + count
- base model name + version
- exact hyper-parameters
- pairwise accuracy on the held-out 10%
- timestamp

Pair this with the `evaluate.py` output (MRR/NDCG/Recall@k vs
baselines) for a publishable result.
