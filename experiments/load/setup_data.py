"""Seed the load-test stack (#227): synthetic PDFs, uploaded through the API.

Writes `.data/upload.pdf` (the 10-page file the upload scenario sends) and `.data/books.json`
(ids of seeded, fully ingested books). Synthetic text: repeated sentences with a varying topic
word per page, so the full-text and vector legs have something to match.
Run: uv run --frozen python experiments/load/setup_data.py --api http://localhost:18000
"""

import argparse
import io
import json
import random
import time
from pathlib import Path

import font_roboto
import httpx
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import simpleSplit
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas

FONT = "Roboto"
pdfmetrics.registerFont(
    TTFont(FONT, str(Path(font_roboto.__file__).parent / "files" / "Roboto-Regular.ttf"))
)
TOPICS = ["sông", "núi", "lúa", "triều đình", "thương mại", "làng xã", "đê điều", "chữ Nôm"]
HEADERS = {"X-Dev-User": "load-user"}


def make_pdf(pages: int, seed: int) -> bytes:
    rng = random.Random(seed)
    buffer = io.BytesIO()
    canvas = Canvas(buffer, pageSize=A4)
    for n in range(pages):
        canvas.bookmarkPage(f"b{n}")
        canvas.addOutlineEntry(f"Chương {n + 1}", f"b{n}", level=0)
        canvas.setFont(FONT, 16)
        canvas.drawString(40, 800, f"Chương {n + 1}")
        canvas.setFont(FONT, 11)
        topic = rng.choice(TOPICS)
        body = (
            f"Người dân vùng {topic} sống bằng nghề trồng lúa và đánh cá, theo ghi chép số {n}. "
            f"Mùa màng phụ thuộc vào {rng.choice(TOPICS)} và thời tiết. "
        ) * 12
        y = 770.0
        for line in simpleSplit(body, FONT, 11, 515):
            canvas.drawString(40, y, line)
            y -= 15
        canvas.showPage()
    canvas.save()
    return buffer.getvalue()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", default="http://localhost:18000")
    parser.add_argument("--books", type=int, default=10)
    parser.add_argument("--pages", type=int, default=30)
    args = parser.parse_args()
    out = Path(__file__).parent / ".data"
    out.mkdir(exist_ok=True)
    (out / "upload.pdf").write_bytes(make_pdf(10, seed=999))
    ids, jobs = [], []
    with httpx.Client(base_url=args.api, headers=HEADERS, timeout=60) as client:
        for i in range(args.books):
            r = client.post(
                "/books",
                files={"file": (f"seed{i}.pdf", make_pdf(args.pages, seed=i), "application/pdf")},
                data={"title": f"Sách thử {i}"},
            )
            r.raise_for_status()
            ids.append(r.json()["book"]["id"])
            jobs.append(r.json()["job_id"])
        deadline = time.time() + 600
        pending = set(jobs)
        while pending and time.time() < deadline:
            for j in list(pending):
                st = client.get(f"/ingestion-jobs/{j}").json()
                if st["status"] in ("succeeded", "failed"):
                    pending.discard(j)
                    if st["status"] == "failed":
                        raise SystemExit(f"seed job failed: {st['error']}")
            time.sleep(2)
        if pending:
            raise SystemExit("seed ingestion did not finish in 10 minutes")
    (out / "books.json").write_text(json.dumps(ids))
    print(f"seeded {len(ids)} books x {args.pages} pages")


if __name__ == "__main__":
    main()
