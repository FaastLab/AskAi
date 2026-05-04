"""Fine-tune a cross-encoder reranker on (query, positive, negative) triplets.

Uses sentence-transformers' built-in CrossEncoder + the Multiple
Negatives Ranking-style loss adapted for cross-encoders. For ~5000
triplets and base-sized starting checkpoint, expect ~30 min on a 3090.

Output: a Hugging Face model directory you can:
- Push: `huggingface-cli upload <repo> <local-dir>`
- Use locally by setting `BGE_RERANKER_MODEL=/abs/path/to/dir` in .env

Reproducibility note: deterministic seeds + a small `train_log.json`
beside the weights records the data file, base model, hyper-params,
and final eval scores — exactly the artifact you'd cite in a thesis.
"""

from __future__ import annotations

import argparse
import json
import random
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sentence_transformers.cross_encoder import CrossEncoder
    from torch.utils.data import DataLoader


@dataclass(slots=True)
class TrainConfig:
    triplets_path: str = "training/triplets.jsonl"
    base_model: str = "BAAI/bge-reranker-base"
    output_dir: str = "training/finreg-reranker-v1"
    epochs: int = 3
    batch_size: int = 16
    learning_rate: float = 2.0e-5
    eval_split: float = 0.1
    seed: int = 42


def train(config: TrainConfig) -> None:
    """Run the fine-tune. Returns nothing; writes weights + train_log.json."""
    try:
        from sentence_transformers import (
            CrossEncoder,
            InputExample,
            losses,
        )
        from torch.utils.data import DataLoader
    except ImportError as exc:  # pragma: no cover - runtime hint
        raise SystemExit(
            "Training needs sentence-transformers + torch. Install:\n"
            "  uv pip install -e 'packages/search[bge-reranker]'"
        ) from exc

    random.seed(config.seed)
    triplets = _load_triplets(config.triplets_path)
    if len(triplets) < 50:
        raise SystemExit(
            f"Only {len(triplets)} triplets — generate at least 500 first."
        )

    train_examples, eval_examples = _split(triplets, config.eval_split, config.seed)
    print(
        f"Loaded {len(triplets)} triplets → {len(train_examples)} train / "
        f"{len(eval_examples)} eval"
    )

    # Cross-encoder training treats this as a binary relevance task:
    # positive pair has label 1.0, negative pair label 0.0.
    examples: list[InputExample] = []
    for t in train_examples:
        examples.append(InputExample(texts=[t["query"], t["positive"]], label=1.0))
        examples.append(InputExample(texts=[t["query"], t["negative"]], label=0.0))

    model = CrossEncoder(config.base_model, num_labels=1)
    loader: DataLoader = DataLoader(
        examples, shuffle=True, batch_size=config.batch_size
    )

    model.fit(
        train_dataloader=loader,
        epochs=config.epochs,
        optimizer_params={"lr": config.learning_rate},
        warmup_steps=int(len(loader) * 0.1),
        output_path=config.output_dir,
        show_progress_bar=True,
    )

    eval_metrics = _evaluate(model, eval_examples)
    log = {
        "config": asdict(config),
        "eval_metrics": eval_metrics,
        "n_triplets": len(triplets),
        "trained_at": datetime.now(UTC).isoformat(),
    }
    Path(config.output_dir, "train_log.json").write_text(
        json.dumps(log, indent=2), encoding="utf-8"
    )
    print(f"\n✓ Wrote weights + train_log.json to {config.output_dir}")
    print("  Eval:", eval_metrics)


def _load_triplets(path: str | Path) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    with Path(path).open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def _split(
    triplets: list[dict[str, str]], eval_split: float, seed: int
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    rng = random.Random(seed)
    shuffled = triplets[:]
    rng.shuffle(shuffled)
    split = int(len(shuffled) * (1 - eval_split))
    return shuffled[:split], shuffled[split:]


def _evaluate(
    model: "CrossEncoder", eval_examples: list[dict[str, str]]
) -> dict[str, float]:
    """Pairwise accuracy: does the model score positive > negative?"""
    correct = 0
    for t in eval_examples:
        scores = model.predict(
            [(t["query"], t["positive"]), (t["query"], t["negative"])]
        )
        if scores[0] > scores[1]:
            correct += 1
    return {
        "pairwise_accuracy": (correct / max(len(eval_examples), 1)),
        "n_eval_pairs": len(eval_examples),
    }


# ---- CLI -------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(prog="askai-rerank-train")
    parser.add_argument("--triplets", default="training/triplets.jsonl")
    parser.add_argument(
        "--base-model", default="BAAI/bge-reranker-base"
    )
    parser.add_argument("--output-dir", default="training/finreg-reranker-v1")
    parser.add_argument("--epochs", type=int, default=3)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--learning-rate", type=float, default=2e-5)
    parser.add_argument("--eval-split", type=float, default=0.1)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    train(
        TrainConfig(
            triplets_path=args.triplets,
            base_model=args.base_model,
            output_dir=args.output_dir,
            epochs=args.epochs,
            batch_size=args.batch_size,
            learning_rate=args.learning_rate,
            eval_split=args.eval_split,
            seed=args.seed,
        )
    )


if __name__ == "__main__":
    main()
