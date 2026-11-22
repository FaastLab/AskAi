"""Does row-aware Excel chunking actually help retrieval? Measure it.

Builds a synthetic (fictional) engineering-standards register, then
indexes it three ways and asks the same questions of each:

  A. flat+cap  — what a generic indexer does: the workbook becomes one
                 text document, extraction stops at a character cap
                 (default 4,000,000, Azure AI Search's per-document
                 limit on higher tiers), then fixed-size chunking.
  B. flat      — same flattening and fixed-size chunking, no cap.
  C. row       — AskAi's XlsxParser + RowChunker: one chunk per row,
                 every value labelled with its column header.

Retrieval is plain BM25 (no embeddings, no API keys) so the script runs
anywhere in seconds and the comparison isolates the chunking strategy.
A hit means the target row's standard code appears in the retrieved
chunk — generous to A/B, whose chunks contain several rows.

    uv run python scripts/eval_xlsx_chunking.py
    uv run python scripts/eval_xlsx_chunking.py --rows 10000 --cap-chars 500000
"""

from __future__ import annotations

import argparse
import math
import random
import re
import sys
import time
from collections import Counter
from dataclasses import dataclass
from datetime import date, timedelta
from io import BytesIO

from openpyxl import Workbook

from faastlab_askai_indexing.chunkers.row import RowChunker
from faastlab_askai_indexing.parsers.xlsx import XlsxParser

HEADERS = ["Code", "Title", "Discipline", "Owner", "Issued", "Status", "Applies To"]
DISCIPLINES = ["Track", "Signalling", "Electrification", "Civils", "Drainage", "Telecoms",
               "Structures", "Earthworks", "Stations", "Rolling Stock", "Plant", "Fire Safety"]
ASSETS = ["ballast", "sleepers", "points", "cabling", "culverts", "bridges", "tunnels",
          "platforms", "canopies", "masts", "transformers", "fencing", "level crossings",
          "embankments", "retaining walls", "lighting", "lifts", "escalators", "depots",
          "footbridges", "drains", "gantries", "switchgear", "batteries", "CCTV"]
ACTIVITIES = ["inspection", "maintenance", "renewal", "design", "testing", "installation",
              "monitoring", "decommissioning", "commissioning", "repair", "survey",
              "risk assessment", "handover", "cleaning", "refurbishment"]
CONTEXTS = ["urban routes", "rural lines", "coastal sites", "high-speed lines", "freight yards",
            "heritage structures", "flood zones", "night possessions", "winter conditions",
            "tunnels under 1km", "single-track sections", "junctions", "sidings", "viaducts",
            "electrified sections", "non-electrified sections", "station approaches",
            "cuttings", "low bridges", "depot roads"]
CLASSES = ["risk class A", "risk class B", "risk class C", "risk class D",
           "risk class E", "risk class F", "risk class G", "risk class H"]
TEAMS = ["Asset Engineering", "Route Delivery", "Safety Assurance", "Maintenance Planning",
         "Design Authority", "Capital Projects", "Operations Control", "Standards Office"]
STATUSES = ["Current", "Current", "Current", "Under Review", "Withdrawn", "Draft"]


@dataclass(slots=True)
class Row:
    code: str
    title: str
    discipline: str
    owner: str
    issued: date
    status: str
    applies_to: str


def build_rows(n: int, seed: int) -> list[Row]:
    rng = random.Random(seed)
    combos = [(a, b, c, k) for a in ASSETS for b in ACTIVITIES for c in CONTEXTS for k in CLASSES]
    rng.shuffle(combos)
    if n > len(combos):
        sys.exit(f"--rows max is {len(combos)} (unique titles)")
    rows = []
    for i, (asset, activity, ctx, cls) in enumerate(combos[:n], start=1):
        rows.append(Row(
            code=f"STD-{i:05d}",
            title=f"{activity.capitalize()} of {asset} on {ctx}, {cls}",
            discipline=rng.choice(DISCIPLINES),
            owner=rng.choice(TEAMS),
            issued=date(2005, 1, 1) + timedelta(days=rng.randrange(7300)),
            status=rng.choice(STATUSES),
            applies_to=rng.choice(["All routes", "Southern region", "Northern region",
                                   "Scotland", "Wales", "Eastern region", "Western region"]),
        ))
    return rows


def to_xlsx(rows: list[Row]) -> bytes:
    wb = Workbook(write_only=True)
    ws = wb.create_sheet("Register")
    ws.append(HEADERS)
    for r in rows:
        ws.append([r.code, r.title, r.discipline, r.owner, r.issued, r.status, r.applies_to])
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def flatten(rows: list[Row]) -> str:
    """Mimic a generic extractor: cell values joined, headers once at the top."""
    lines = [" ".join(HEADERS)]
    for r in rows:
        lines.append(" ".join([r.code, r.title, r.discipline, r.owner,
                               r.issued.isoformat(), r.status, r.applies_to]))
    return "\n".join(lines)


def fixed_chunks(text: str, size: int, overlap: int) -> list[str]:
    step = size - overlap
    return [text[i:i + size] for i in range(0, len(text), step)]


_TOKEN = re.compile(r"[a-z0-9]+")
_STOP = {"the", "of", "on", "for", "and", "which", "who", "what", "when",
         "was", "is", "does", "standard", "team", "own", "owns", "issued"}


def tokenize(s: str) -> list[str]:
    return [t for t in _TOKEN.findall(s.lower()) if t not in _STOP]


class BM25:
    def __init__(self, docs: list[str], k1: float = 1.5, b: float = 0.75) -> None:
        self.k1, self.b = k1, b
        self.tfs = [Counter(tokenize(d)) for d in docs]
        self.lens = [sum(tf.values()) for tf in self.tfs]
        self.avg = sum(self.lens) / max(1, len(self.lens))
        df: Counter[str] = Counter()
        for tf in self.tfs:
            df.update(tf.keys())
        n = len(docs)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}
        self.postings: dict[str, list[int]] = {}
        for i, tf in enumerate(self.tfs):
            for t in tf:
                self.postings.setdefault(t, []).append(i)

    def search(self, query: str, k: int = 10) -> list[int]:
        scores: dict[int, float] = {}
        for t in set(tokenize(query)):
            idf = self.idf.get(t)
            if idf is None:
                continue
            for i in self.postings[t]:
                f = self.tfs[i][t]
                denom = f + self.k1 * (1 - self.b + self.b * self.lens[i] / self.avg)
                scores[i] = scores.get(i, 0.0) + idf * f * (self.k1 + 1) / denom
        return sorted(scores, key=scores.__getitem__, reverse=True)[:k]


def make_questions(rows: list[Row], n: int, seed: int) -> list[tuple[str, Row]]:
    rng = random.Random(seed + 1)
    templates = [
        "Which team owns the standard for {t}?",
        "When was the standard on {t} issued?",
        "What is the status of the {t} standard?",
        "Which discipline covers {t}?",
    ]
    picks = rng.sample(rows, n)
    return [(rng.choice(templates).format(t=r.title.lower()), r) for r in picks]


def evaluate(label: str, chunks: list[str], questions: list[tuple[str, Row]]) -> dict[str, float]:
    t0 = time.perf_counter()
    index = BM25(chunks)
    build_s = time.perf_counter() - t0
    r1 = r5 = mrr = 0.0
    for q, row in questions:
        hits = index.search(q, k=10)
        for rank, idx in enumerate(hits, start=1):
            if row.code in chunks[idx]:
                r1 += rank == 1
                r5 += rank <= 5
                mrr += 1 / rank
                break
    n = len(questions)
    return {"label": label, "chunks": len(chunks), "recall@1": r1 / n,
            "recall@5": r5 / n, "mrr@10": mrr / n, "build_s": build_s}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rows", type=int, default=40_000)
    ap.add_argument("--questions", type=int, default=200)
    ap.add_argument("--cap-chars", type=int, default=4_000_000)
    ap.add_argument("--chunk-chars", type=int, default=1000)
    ap.add_argument("--overlap-chars", type=int, default=100)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--save-xlsx", help="write the synthetic workbook here")
    args = ap.parse_args()

    rows = build_rows(args.rows, args.seed)
    xlsx = to_xlsx(rows)
    if args.save_xlsx:
        with open(args.save_xlsx, "wb") as f:
            f.write(xlsx)
    questions = make_questions(rows, args.questions, args.seed)

    flat = flatten(rows)
    capped = flat[: args.cap_chars]
    cut_rows = sum(1 for r in rows if r.code not in capped)

    doc = XlsxParser().parse(xlsx, filename="register.xlsx")
    row_chunks = [c.text for c in RowChunker(token_counter=lambda s: len(s) // 4).chunk(doc)]

    results = [
        evaluate("A. flat + cap", fixed_chunks(capped, args.chunk_chars, args.overlap_chars), questions),
        evaluate("B. flat", fixed_chunks(flat, args.chunk_chars, args.overlap_chars), questions),
        evaluate("C. row (AskAi)", row_chunks, questions),
    ]

    print(f"\nWorkbook: {args.rows:,} rows, {len(xlsx) / 1e6:.1f} MB xlsx, "
          f"{len(flat):,} chars when flattened")
    print(f"Cap: {args.cap_chars:,} chars -> {cut_rows:,} rows "
          f"({cut_rows / len(rows):.0%}) never reach the index in strategy A")
    print(f"Questions: {len(questions)} (BM25, top 10)\n")
    print(f"{'strategy':<16}{'chunks':>9}{'recall@1':>10}{'recall@5':>10}{'mrr@10':>9}")
    for r in results:
        print(f"{r['label']:<16}{r['chunks']:>9,}{r['recall@1']:>10.1%}"
              f"{r['recall@5']:>10.1%}{r['mrr@10']:>9.3f}")
    print()


if __name__ == "__main__":
    main()
