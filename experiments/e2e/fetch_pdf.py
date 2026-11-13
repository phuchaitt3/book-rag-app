"""Download the Wikisource PDF export of Việt Nam sử lược, Quyển I, for the real-model run (#189).

The text is Trần Trọng Kim's (died 1953), public domain in Vietnam. The export is generated
by Wikisource's ws-export tool, so its bytes can change when the wiki text is edited: the
SHA-256 of the file used for the published figures is in docs/benchmarks/e2e-real-model.md.

  uv run python experiments/e2e/fetch_pdf.py            # writes experiments/e2e/data/vsl.pdf
"""

from __future__ import annotations

import hashlib
import os
import urllib.request
from pathlib import Path

URL = (
    "https://ws-export.wmcloud.org/?format=pdf&lang=vi"
    "&page=Vi%E1%BB%87t_Nam_s%E1%BB%AD_l%C6%B0%E1%BB%A3c%2FQuy%E1%BB%83n_I"
)
OUT = Path(os.environ.get("OUT_DIR", Path(__file__).parent / "data")) / "vsl.pdf"


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(URL, headers={"User-Agent": "book-rag-app-e2e/0.1"})
    with urllib.request.urlopen(request, timeout=300) as response:
        data = response.read()
    if not data.startswith(b"%PDF"):
        raise SystemExit("the export did not return a PDF")
    OUT.write_bytes(data)
    print(f"{OUT}: {len(data):,} bytes, sha256 {hashlib.sha256(data).hexdigest()}")


if __name__ == "__main__":
    main()
