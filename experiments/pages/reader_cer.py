"""Character error rate of the Tesseract reader on the #271 page set (#273). PROVISIONAL.

Usage: python experiments/pages/reader_cer.py <pages_dir> <out_json> [--set heldout|dev|all]

Reads each page image with `TesseractReader("vie+eng")` and compares with `text/<id>.txt` after NFC
normalisation and whitespace collapsing. CER = Levenshtein distance / length of the reference.
The page set is only partly checked by the owner (3 of 50 pages, 2026-11-27, #288), so numbers are
provisional. The committed `tesseract-vie-eng-UNCHECKED.json` predates that check.
Set TESSDATA_PREFIX to a folder holding vie.traineddata and eng.traineddata.
"""

from __future__ import annotations

import json
import re
import sys
import time
import unicodedata
from pathlib import Path

from book_rag.reading.tesseract import TesseractReader


def norm(text: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", text)).strip()


def levenshtein(a: str, b: str) -> int:
    if len(a) < len(b):
        a, b = b, a
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def main() -> None:
    pages = Path(sys.argv[1])
    out = Path(sys.argv[2])
    which = sys.argv[sys.argv.index("--set") + 1] if "--set" in sys.argv else "all"
    reader = TesseractReader(
        "vie+eng",
        command=sys.argv[sys.argv.index("--cmd") + 1] if "--cmd" in sys.argv else "tesseract",
    )
    rows = []
    for line in (pages / "manifest.jsonl").read_text(encoding="utf-8").splitlines():
        m = json.loads(line)
        if which != "all" and m["set"] != which:
            continue
        ref = norm((pages / "text" / f"{m['id']}.txt").read_text(encoding="utf-8"))
        t0 = time.time()
        hyp = norm(reader.read((pages / "images" / f"{m['id']}.jpg").read_bytes()))
        secs = time.time() - t0
        dist = levenshtein(ref, hyp)
        rows.append(
            {
                "id": m["id"],
                "set": m["set"],
                "ref_chars": len(ref),
                "hyp": hyp,
                "distance": dist,
                "cer": dist / max(len(ref), 1),
                "seconds": round(secs, 2),
            }
        )
        print(m["id"], f"cer={rows[-1]['cer']:.3f}", f"{secs:.1f}s", flush=True)
    tot_d = sum(r["distance"] for r in rows)
    tot_n = sum(r["ref_chars"] for r in rows)
    summary = {
        "status": "PROVISIONAL (owner checked 3 of 50 pages, #288)",
        "reader": f"{reader.name} {reader.version}",
        "pages": len(rows),
        "micro_cer": tot_d / max(tot_n, 1),
        "mean_cer": sum(r["cer"] for r in rows) / max(len(rows), 1),
        "median_seconds": sorted(r["seconds"] for r in rows)[len(rows) // 2] if rows else None,
    }
    out.write_text(
        json.dumps({"summary": summary, "pages": rows}, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
