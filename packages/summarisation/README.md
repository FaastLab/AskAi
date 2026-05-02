# `faastlab-askai-summarisation`

Phase 4 — implemented.

## What lives here

```
src/faastlab_askai_summarisation/
├── prompts.py      # MAP / REDUCE / FOCUSED / KEYPHRASE prompts
├── map_reduce.py   # Token-aware slicing + parallel map + reduce
├── keyphrases.py   # JSON-array keyphrase extraction with tolerant parser
├── service.py      # SummarisationService — load chunks, run, persist
├── tasks.py        # Celery task: askai.summarisation.summarise_document
└── cli.py          # `python -m faastlab_askai_summarisation.cli`
```

## Run a summary

```bash
# All un-summarised docs in the tenant
make summarise TENANT=demo-public

# Single doc by UUID
make summarise TENANT=demo-public DOCUMENT=<uuid>

# Force re-summarise even if a summary already exists
make summarise TENANT=demo-public FORCE=1
```

The result is written back to:
- `documents.summary` (text)
- `documents.keyphrases` (JSON array of strings)

## How it works

1. Load all chunks for the document, ordered by `char_start`, joined.
2. Slice into ≤2500-token windows with 100-token overlap (tiktoken).
3. **Map**: parallel LLM call per slice → 3–6 sentence slice summary.
4. **Reduce**: one final LLM call combining slice summaries into a
   coherent whole-document summary (skipped if there's only one slice).
5. **Keyphrases**: one more LLM call asking for a JSON array of 6–12
   distinctive phrases, parsed tolerantly.
6. Persist to the `documents` row.

## Focused (query-biased) summary

`SummarisationService.focused_summarise()` takes a stored summary and
re-summarises it with a topical bias — useful for "summarise X with
respect to Y" questions in the chat UI.
