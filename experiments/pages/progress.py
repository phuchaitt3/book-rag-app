"""Print the proofreading progress (`Tiến triển`) of the Index pages of candidates.json books."""

import json
import re
import sys
from pathlib import Path

from wikisource import api

rows = [
    r
    for r in json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    if re.search(r"PD-old-\d+-expired", r["categories"]) and (r["pagecount"] or 0) >= 30
]
for i in range(0, len(rows), 40):
    chunk = rows[i : i + 40]
    res = api(
        action="query",
        prop="revisions",
        rvprop="content",
        rvslots="main",
        titles="|".join("Mục lục:" + r["file"] for r in chunk),
    )
    for p in res["query"]["pages"].values():
        text = p["revisions"][0]["slots"]["main"]["*"]
        m = re.search(r"\|Tiến triển=(\w*)", text)
        file = p["title"].split(":", 1)[1]
        r = next(x for x in chunk if x["file"] == file)
        print(m.group(1) if m else "?", file, r["pagecount"], r["date"])
