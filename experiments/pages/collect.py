"""Collect 50 proofread Vietnamese Wikisource pages with their scan images (#271).

10 books, 5 pages each: 4 held-out and 1 dev page per book (seed 271). Only books whose Commons
file page states an old public-domain basis (a `PD-old-*-expired` category) are used; the licence
basis is read from the live Commons metadata at collection time and stored per page in
manifest.jsonl. Pages must be proofread or validated (`pagequality` level 3 or 4) and hold
600 to 2500 characters of prose after cleaning, so a question can be answered from one page.

    python collect.py OUT_DIR

OUT_DIR gets `images/<id>.jpg`, `text/<id>.txt` (the Wikisource text, cleaned of markup) and
`manifest.jsonl`. Nothing here is committed: OUT_DIR is put under DVC (see README next to it).
"""

import hashlib
import json
import random
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from wikisource import api, download

# All have Index progress V (validated) on vi.wikisource; 10 are used, the rest are spares.
BOOKS = [
    "Canh hoa diem tuyet.pdf",
    "Chuyen the gian 1.pdf",
    "Co xuy nguyen am.pdf",
    "Dai guong truyen.pdf",
    "Gương sử Nam - Hoàng Thái-Xuyên (1910).pdf",
    "Hung Dao Vuong.pdf",
    "Linh Nam dat su 1.pdf",
    "Luan ngu 1.pdf",
    "Cuu my ky duyen.pdf",
    "Dai guong kinh.pdf",
    "Long nguoi nham hiem.pdf",
    "Nhu tay nhut trinh.pdf",
]
N_BOOKS = 10
PER_BOOK, DEV_PER_BOOK, SEED = 5, 1, 271
MIN_CHARS, MAX_CHARS = 600, 2500
IMAGE_WIDTH = 1500


def clean(wikitext: str) -> tuple[int | None, str]:
    """Return the page-quality level and the plain text of a Trang: page's wikitext."""
    m = re.search(r'<pagequality level="(\d)"', wikitext)
    level = int(m.group(1)) if m else None
    body = re.sub(r"<noinclude>.*?</noinclude>", "", wikitext, flags=re.S)
    body = re.sub(r"<pagequality[^>]*/>", "", body)
    body = re.sub(r"<section[^>]*/>|</?poem>", "", body)
    body = re.sub(r"</?noinclude>|</?includeonly>|<references\s*/>", "", body)
    body = re.sub(r"\{\{[^{}]*\}\}", "", body)  # simple templates (headers, rules)
    body = re.sub(r"'''?", "", body)
    return level, re.sub(r"\n{3,}", "\n\n", body).strip()


def book_info(file: str) -> dict[str, Any]:
    res = api(
        action="query",
        prop="imageinfo",
        iiprop="url|size|extmetadata",
        titles=f"File:{file}",
    )
    page = next(iter(res["query"]["pages"].values()))
    info = page["imageinfo"][0]
    meta = info["extmetadata"]
    cats = meta["Categories"]["value"].split("|")
    pd_old = [c for c in cats if c.startswith("PD-old-") and c.endswith("-expired")]
    if not pd_old:
        raise SystemExit(f"{file}: no PD-old-*-expired category on Commons; not usable")
    return {
        "file": file,
        "commons_url": info["descriptionurl"],
        "pagecount": info["pagecount"],
        "date": meta.get("DateTimeOriginal", {}).get("value"),
        "license_short_name": meta["LicenseShortName"]["value"],
        "pd_categories": pd_old,
        "credit": re.sub(r"<[^>]+>", "", meta.get("Credit", {}).get("value", ""))[:200],
        "artist": re.sub(r"<[^>]+>", "", meta.get("Artist", {}).get("value", ""))[:120],
    }


def candidate_pages(file: str, pagecount: int, rng: random.Random, n: int = 60) -> list[int]:
    lo, hi = max(3, int(pagecount * 0.1)), max(4, int(pagecount * 0.9))
    pages = list(range(lo, hi + 1))
    rng.shuffle(pages)
    return pages[:n]


def fetch_pages(file: str, numbers: list[int]) -> dict[int, dict[str, Any]]:
    out: dict[int, dict[str, Any]] = {}
    for i in range(0, len(numbers), 25):
        chunk = numbers[i : i + 25]
        res = api(
            action="query",
            prop="revisions",
            rvprop="content|ids",
            rvslots="main",
            titles="|".join(f"Trang:{file}/{n}" for n in chunk),
        )
        for p in res["query"]["pages"].values():
            if "revisions" not in p:
                continue
            rev = p["revisions"][0]
            n = int(p["title"].rsplit("/", 1)[1])
            level, text = clean(rev["slots"]["main"]["*"])
            out[n] = {"title": p["title"], "revid": rev["revid"], "level": level, "text": text}
    return out


def image_url(file: str, number: int) -> str:
    res = api(
        action="query",
        prop="imageinfo",
        iiprop="url",
        iiurlwidth=IMAGE_WIDTH,
        iiurlparam=f"page{number}-{IMAGE_WIDTH}px",
        titles=f"File:{file}",
    )
    page = next(iter(res["query"]["pages"].values()))
    return page["imageinfo"][0]["thumburl"]  # type: ignore[no-any-return]


def main() -> None:
    out = Path(sys.argv[1])
    (out / "images").mkdir(parents=True, exist_ok=True)
    (out / "text").mkdir(exist_ok=True)
    rng = random.Random(SEED)
    rows: list[dict[str, Any]] = []
    when = datetime.now(UTC).isoformat(timespec="seconds")
    bi = 0
    for file in BOOKS:
        if bi == N_BOOKS:
            break
        info = book_info(file)
        got = fetch_pages(file, candidate_pages(file, info["pagecount"], rng))
        good = [
            n
            for n, p in sorted(got.items())
            if p["level"] in (3, 4) and MIN_CHARS <= len(p["text"]) <= MAX_CHARS
        ]
        if len(good) < PER_BOOK:
            print(f"skip {file}: only {len(good)} usable pages among the candidates")
            continue
        rng.shuffle(good)
        for k, n in enumerate(good[:PER_BOOK]):
            p = got[n]
            pid = f"b{bi:02d}p{n:03d}"
            img = out / "images" / f"{pid}.jpg"
            url = image_url(file, n)
            download(url, str(img))
            (out / "text" / f"{pid}.txt").write_text(p["text"] + "\n", encoding="utf-8")
            rows.append(
                {
                    "id": pid,
                    "set": "dev" if k < DEV_PER_BOOK else "heldout",
                    "page": n,
                    "source_url": f"https://vi.wikisource.org/wiki/{p['title'].replace(' ', '_')}",
                    "wikisource_revision": p["revid"],
                    "proofread_level": p["level"],
                    "image_url": url,
                    "image_sha256": hashlib.sha256(img.read_bytes()).hexdigest(),
                    "text_chars": len(p["text"]),
                    "licence_basis": (
                        f"Commons file page {info['commons_url']}: "
                        f"{info['license_short_name']}, categories "
                        f"{', '.join(info['pd_categories'])}"
                    ),
                    "book": info,
                    "collected_at": when,
                    "licence_approved_by_owner": False,
                }
            )
        bi += 1
    with (out / "manifest.jsonl").open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    held = sum(r["set"] == "heldout" for r in rows)
    print(f"{len(rows)} pages: {held} held-out, {len(rows) - held} dev")


if __name__ == "__main__":
    main()
