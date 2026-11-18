"""List Wikisource scans whose Commons file page states an old public-domain basis (#271).

Writes candidates.json: file name, Commons URL, date, license short name, categories, page count.
Usage: python scan_candidates.py OUT.json [MAX_INDEXES]
"""

import json
import sys

from wikisource import api


def index_files(limit: int) -> list[str]:
    names: list[str] = []
    cont: dict[str, str] = {}
    while len(names) < limit:
        res = api(action="query", list="allpages", apnamespace=106, aplimit=500, **cont)
        for p in res["query"]["allpages"]:
            t = p["title"].split(":", 1)[1]
            if t.lower().endswith(".pdf") and "/" not in t:
                names.append(t)
        if "continue" not in res:
            break
        cont = {"apcontinue": res["continue"]["apcontinue"]}
    return names[:limit]


def main() -> None:
    out, limit = sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 1500
    names = index_files(limit)
    rows = []
    for i in range(0, len(names), 40):
        chunk = names[i : i + 40]
        res = api(
            action="query",
            prop="imageinfo",
            iiprop="url|size|extmetadata",
            titles="|".join("File:" + n for n in chunk),
        )
        for page in res["query"]["pages"].values():
            info = (page.get("imageinfo") or [None])[0]
            if not info:
                continue
            meta = info.get("extmetadata", {})
            cats = meta.get("Categories", {}).get("value", "")
            rows.append(
                {
                    "file": page["title"].split(":", 1)[1],
                    "commons": info.get("descriptionurl"),
                    "pagecount": info.get("pagecount"),
                    "date": meta.get("DateTimeOriginal", {}).get("value"),
                    "license": meta.get("LicenseShortName", {}).get("value"),
                    "categories": cats,
                    "artist": meta.get("Artist", {}).get("value", "")[:200],
                }
            )
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(rows, fh, ensure_ascii=False, indent=1)
    old = [r for r in rows if "PD-old" in r["categories"]]
    print(len(names), "indexes,", len(rows), "with file info,", len(old), "with a PD-old category")


if __name__ == "__main__":
    main()
