"""Dump the prompt the app builds for each of the 208 serving questions (#245).

Run `capture_stub.py` on the host and the app with `LLM_PROVIDER=openai` pointing at it, then:

    BOOK_ID=<uuid> python experiments/serving/dump_prompts.py CAPTURED.jsonl OUT.jsonl

LIMIT=n sends only the first n questions (smoke run).

Questions are sent one at a time, so the i-th captured request belongs to the i-th question.
OUT holds one line per question: id, question, the best passage's score and the chat `messages`
(system and user) the app sent, with the retrieved passages inside the user message. The app must
run with abstaining off, or a refused question sends no prompt. Standard library only.
"""

import json
import os
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent


def lines(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def ask(api: str, book_id: str, question: str) -> float | None:
    """Send one question; return the best passage's score from the `citations` event."""
    req = urllib.request.Request(
        f"{api.rstrip('/')}/books/{book_id}/chat",
        data=json.dumps({"question": question, "top_k": 6}).encode(),
        headers={
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
            "X-Dev-User": os.environ.get("DEV_USER", "dev-user"),
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=300) as resp:
        body = resp.read().decode()
    for block in body.split("\n\n"):
        if block.startswith("event: citations\n"):
            cites = json.loads(block.split("\ndata: ", 1)[1])
            return cites[0]["score"] if cites else None
    return None


def main() -> None:
    captured, out = Path(sys.argv[1]), Path(sys.argv[2])
    api = os.environ.get("API_URL", "http://localhost:8000")
    book_id = os.environ["BOOK_ID"]
    questions = json.loads((HERE / "questions-208.json").read_text(encoding="utf-8"))
    rows = []
    limit = int(os.environ.get("LIMIT", "0"))
    for i, q in enumerate(questions[:limit] if limit else questions):
        score = ask(api, book_id, q["question"])
        got = lines(captured)
        if len(got) != i + 1:
            sys.exit(
                f"question {i} ({q['id']}): expected {i + 1} captured prompts, found {len(got)}"
            )
        rows.append(
            {
                "id": q["id"],
                "question": q["question"],
                "top_score": score,
                "messages": got[-1]["messages"],
            }
        )
    out.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8"
    )
    print(f"wrote {len(rows)} prompts to {out}")


if __name__ == "__main__":
    main()
