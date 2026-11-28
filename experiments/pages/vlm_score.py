"""Score the VLM reader's output against the #271 page texts (#273). PROVISIONAL.

Usage: python experiments/pages/vlm_score.py <pages_dir> <results_dir> <out_json>

`<results_dir>` holds the `vlm-<config>.jsonl` files of the Kaggle kernel. Normalisation and CER are
those of `reader_cer.py`. A page the kernel failed on counts as an empty transcription. For
held-out pages it also reports a 95% bootstrap interval resampling the books (seed 273), the same
for the committed Tesseract output, the paired difference and a diacritic-stripped CER.
"""

from __future__ import annotations

import json
import random
import sys
import unicodedata
from collections import defaultdict
from collections.abc import Callable
from pathlib import Path

from reader_cer import levenshtein, norm

SEED = 273
RESAMPLES = 10_000
TESSERACT = Path(__file__).parent / "results" / "tesseract-vie-eng-UNCHECKED.json"


def strip_marks(text: str) -> str:
    decomposed = unicodedata.normalize("NFD", text.replace("đ", "d").replace("Đ", "D"))
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def micro(rows: list[dict], key: str = "distance", total: str = "ref_chars") -> float:
    return sum(r[key] for r in rows) / sum(r[total] for r in rows)


def bootstrap(rows: list[dict], stat: Callable[[list[dict]], float]) -> list[float]:
    """95% percentile interval of `stat`, resampling whole books (pages of a book are alike)."""
    books: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        books[r["id"].split("p")[0]].append(r)
    names = sorted(books)
    rng = random.Random(SEED)
    values = sorted(
        stat([r for name in rng.choices(names, k=len(names)) for r in books[name]])
        for _ in range(RESAMPLES)
    )
    return [values[int(0.025 * RESAMPLES)], values[int(0.975 * RESAMPLES) - 1]]


def main() -> None:
    pages, results, out = (Path(a) for a in sys.argv[1:4])
    tess = {r["id"]: r for r in json.loads(TESSERACT.read_text(encoding="utf-8"))["pages"]}
    report: dict = {"status": "PROVISIONAL (owner checked 3 of 50 pages, #288)", "configs": {}}
    for path in sorted(results.glob("vlm-*.jsonl")):
        rows = []
        for line in path.read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            ref = norm((pages / "text" / f"{r['id']}.txt").read_text(encoding="utf-8"))
            hyp = norm(r.get("text", ""))
            # Tesseract's text is scored here against the same reference, so the pairs are exact.
            t_hyp = norm(tess[r["id"]]["hyp"])
            rows.append(
                {
                    **r,
                    "ref_chars": len(ref),
                    "distance": levenshtein(ref, hyp),
                    "stripped_distance": levenshtein(strip_marks(ref), strip_marks(hyp)),
                    "stripped_chars": len(strip_marks(ref)),
                    "tesseract_distance": levenshtein(ref, t_hyp),
                }
            )
        done = [r for r in rows if "error" not in r]
        entry: dict = {
            "pages": len(rows),
            "errors": len(rows) - len(done),
            "hit_token_limit": sum(r["hit_limit"] for r in done),
            "median_seconds": sorted(r["seconds"] for r in done)[len(done) // 2] if done else None,
            "peak_vram_mib": max((r["peak_vram_mib"] for r in done), default=None),
        }
        for split in sorted({r["set"] for r in rows}):
            part = [r for r in rows if r["set"] == split]
            entry[split] = {
                "n": len(part),
                "micro_cer": micro(part),
                "mean_cer": sum(r["distance"] / r["ref_chars"] for r in part) / len(part),
                "stripped_micro_cer": micro(part, "stripped_distance", "stripped_chars"),
                "tesseract_micro_cer": micro(part, "tesseract_distance"),
            }
            if split == "heldout":
                entry[split]["ci95"] = bootstrap(part, micro)
                entry[split]["tesseract_ci95"] = bootstrap(
                    part, lambda s: micro(s, "tesseract_distance")
                )
                entry[split]["vlm_minus_tesseract"] = micro(part) - micro(
                    part, "tesseract_distance"
                )
                entry[split]["difference_ci95"] = bootstrap(
                    part, lambda s: micro(s) - micro(s, "tesseract_distance")
                )
        entry["rows"] = rows
        report["configs"][path.stem.removeprefix("vlm-")] = entry
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    for name, e in report["configs"].items():
        print(name, json.dumps({k: v for k, v in e.items() if k != "rows"}))


if __name__ == "__main__":
    main()
