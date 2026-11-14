"""Compare two retrieval_check.py result files question by question (#241).

Prints Hit@1, Hit@5 and MRR over the cited chunks (top_k 6, so MRR@6) with bootstrap 95%
intervals, and the paired difference B minus A (resampling questions, same seed).

  uv run python experiments/e2e/retrieval_compare.py A.json B.json
"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path


def load(path: str) -> dict[str, int | None]:
    rows = json.loads(Path(path).read_text(encoding="utf-8"))["results"]
    return {r["id"]: r["rank"] for r in rows}


def metrics(rank: int | None) -> tuple[float, float, float]:
    return (
        float(rank is not None and rank <= 1),
        float(rank is not None and rank <= 5),
        0.0 if rank is None else 1 / rank,
    )


def ci(values: list[float], seed: int = 241, reps: int = 10_000) -> tuple[float, float]:
    rng = random.Random(seed)
    n = len(values)
    means = sorted(sum(values[rng.randrange(n)] for _ in range(n)) / n for _ in range(reps))
    return means[int(0.025 * reps)], means[int(0.975 * reps)]


def main(a_path: str, b_path: str) -> None:
    a, b = load(a_path), load(b_path)
    ids = sorted(set(a) & set(b))
    print(f"{len(ids)} questions in both")
    names = ("Hit@1", "Hit@5", "MRR@6")
    for label, ranks in (("A", a), ("B", b)):
        cols = [[metrics(ranks[i])[k] for i in ids] for k in range(3)]
        for name, col in zip(names, cols, strict=True):
            low, high = ci(col)
            mean = 100 * sum(col) / len(col)
            print(f"{label} {name}: {mean:.1f} ({100 * low:.1f}-{100 * high:.1f})")
    for k, name in enumerate(names):
        diff = [metrics(b[i])[k] - metrics(a[i])[k] for i in ids]
        low, high = ci(diff)
        mean = 100 * sum(diff) / len(diff)
        print(f"B-A {name}: {mean:+.1f} points ({100 * low:+.1f} to {100 * high:+.1f})")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
