"""Generate the book retrieval test set from chunks.jsonl with the DeepSeek API (#177).

For each sampled chunk (seeded, spread over sections in proportion to their size):
  1. ask      the model sees the chunk and writes one question, its short answer, and the
              sentence of the chunk that answers it (the evidence, copied verbatim).
  2. rewrite  the model sees only that question and rewrites it as a reader who has not
              read the book would ask it, in different words (as #173's "blind" set).
  3. closed   the model answers the question with no book in view.
  4. judge    the model compares the closed-book answer with the reference answer.
Plus a few unanswerable questions, written from a section's title alone and asking what
the book does not say; they carry no gold chunk and are scored apart.

Every call's result is cached in OUT_DIR/gen/<stage>.jsonl, so a rerun only pays for
what is missing; every call's token usage goes to OUT_DIR/gen/usage.jsonl. The final
set is OUT_DIR/questions.jsonl. Run from the repository root:

  uv run --with openai python experiments/book-testset/generate.py --limit 10
  uv run --with openai python experiments/book-testset/generate.py --n 220 --unanswerable 25

Needs DEEPSEEK_API_KEY. DeepSeek's API takes the OpenAI request format, so the openai
package is the client. MODEL overrides the generator; it must differ from any model used
to build an index under test (docs/benchmarks/README.md, checklist item 2).
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path
from typing import Any

OUT = Path(os.environ.get("OUT_DIR", Path(__file__).parent / "data"))
MODEL = os.environ.get("MODEL", "deepseek-v4-pro")
BASE_URL = "https://api.deepseek.com"
SEED = 177
MIN_CHARS = 300  # chunks shorter than this rarely hold a full fact
NO_QUESTIONS_FROM = ("Phụ lục",)  # transliterated Han text: kept in the index, no questions
# USD per million tokens (input on a cache miss, output) at peak hours, an upper bound;
# https://api-docs.deepseek.com/quick_start/pricing, checked 2026-11-10.
PRICES = {
    "deepseek-v4-pro": (1.32, 3.96),
    "deepseek-flash": (0.30, 1.20),
}

SYSTEM = (
    "You help build a test set for a search system over a Vietnamese history book, "
    "Việt Nam sử lược by Trần Trọng Kim (1920s). Write every question and answer in "
    "Vietnamese, in today's spelling (no hyphens between syllables)."
)

ASK = """Here is one passage of the book (section: {path}).

<passage>
{text}
</passage>

Write one question that a reader of this book might ask and that this passage answers.
- Ask about one concrete fact stated in the passage (who, what, when, where, why, how many).
- The question must stand alone: name the people, places or dynasty it is about; never say
  "the passage", "the text" or "this chapter". Use today's spelling, without hyphens.
- Prefer a fact that is particular to this passage over one stated in many places.
- "answer": a short answer (a few words to one sentence).
- "evidence": the one sentence of the passage that answers it, copied exactly, character for
  character, as it appears above (hyphens included)."""

REWRITE = """A question about Vietnamese history:

<question>
{question}
</question>

Rewrite it the way a curious person who has not read any history book would type it into
a search box today.
- Keep the people, places and dynasties it names, and ask for the same kind of answer (if it
  asks which dynasty, still ask which dynasty; do not turn "when" into "which year").
- Change everything else: use your own everyday modern words and synonyms, a different
  sentence structure, and keep at most a third of the other words of the original.
- Use today's spelling, without hyphens between syllables."""

CLOSED = """Answer this question from your own knowledge, in one short sentence. If you do not
know, say "không biết".

<question>
{question}
</question>"""

JUDGE = """Question: {question}
Reference answer: {reference}
Candidate answer: {candidate}

Does the candidate answer give the same essential fact as the reference answer?"""

UNANSWERABLE = """The book has a section titled "{path}". Without its text in view, write one
question in Vietnamese that a reader interested in this period might ask but that a short
1920s history book would almost surely not answer (for example: archaeology or research
after 1930, exact figures nobody recorded, events outside Vietnam and China, or present-day
places and people). It must still sound like a real question about this period."""


STAGES: dict[str, tuple[str, dict[str, Any], str | None]] = {
    # stage: (prompt, example of the JSON object to return, reasoning effort or None for no
    # thinking). DeepSeek's JSON mode needs the word "json" and an example in the prompt
    # (api-docs.deepseek.com/guides/json_mode). Thinking is on by default at high effort and
    # was most of the cost in the smoke test (a one-line rewrite used 1,100 output tokens;
    # writing a question at low effort still used 600-2,200), so no stage thinks: the
    # user's choice for a $2 budget, 2026-11-10. Set a stage's effort to "low" to try it.
    "ask": (ASK, {"question": "...", "answer": "...", "evidence": "..."}, None),
    "rewrite": (REWRITE, {"question": "..."}, None),
    "closed": (CLOSED, {"answer": "..."}, None),
    "judge": (JUDGE, {"same_fact": True}, None),
    "unanswerable": (UNANSWERABLE, {"question": "..."}, None),
}
RETRIES = 2  # JSON mode can return empty content; retry before skipping the item


def norm(text: str) -> str:
    """For matching evidence to chunks: NFC, lowercase, hyphens as spaces, spaces collapsed."""
    text = unicodedata.normalize("NFC", text).lower().replace("-", " ")
    return re.sub(r"\s+", " ", text).strip(" .")


class Cache:
    def __init__(self, stage: str) -> None:
        self.path = OUT / "gen" / f"{stage}.jsonl"
        self.rows: dict[str, dict[str, Any]] = {}
        if self.path.exists():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                row = json.loads(line)
                self.rows[row["key"]] = row["out"]

    def put(self, key: str, out: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"key": key, "out": out}, ensure_ascii=False) + "\n")
        self.rows[key] = out


class Generator:
    def __init__(self, budget_usd: float) -> None:
        from openai import OpenAI  # only needed when a call is made

        if MODEL not in PRICES:  # an unpriced model would count as free and pass the budget
            raise SystemExit(f"no price for {MODEL}: add it to PRICES first")
        key = os.environ.get("DEEPSEEK_API_KEY")
        if not key:
            raise SystemExit("set DEEPSEEK_API_KEY")
        self.client = OpenAI(api_key=key, base_url=BASE_URL)
        self.caches = {s: Cache(s) for s in STAGES}
        self.budget = budget_usd  # for all runs together: usage.jsonl holds earlier spend
        usage = OUT / "gen" / "usage.jsonl"
        self.spent_before = (
            sum(json.loads(x)["usd"] for x in usage.read_text(encoding="utf-8").splitlines())
            if usage.exists()
            else 0.0
        )
        self.spent = self.spent_before
        self.calls = 0

    def run(self, stage: str, key: str, **fields: str) -> dict[str, Any] | None:
        cache = self.caches[stage]
        if key in cache.rows:
            return cache.rows[key]
        if self.spent >= self.budget:
            raise SystemExit(f"budget of ${self.budget:.2f} reached after {self.calls} calls")
        prompt, example, effort = STAGES[stage]
        thinking: dict[str, Any] = (
            {"reasoning_effort": effort, "extra_body": {"thinking": {"type": "enabled"}}}
            if effort
            else {"extra_body": {"thinking": {"type": "disabled"}}}
        )
        content = (
            prompt.format(**fields)
            + "\n\nReply with one json object only, with exactly these keys, for example:\n"
            + json.dumps(example, ensure_ascii=False)
        )
        for _ in range(1 + RETRIES):
            response = self.client.chat.completions.create(
                model=MODEL,
                max_tokens=8000,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": SYSTEM},
                    {"role": "user", "content": content},
                ],
                **thinking,
            )
            self._usage(stage, response.usage)
            choice = response.choices[0]
            try:
                out = json.loads(choice.message.content or "")
            except json.JSONDecodeError:
                continue
            complete = choice.finish_reason == "stop" and isinstance(out, dict)
            if complete and set(example) <= set(out):
                cache.put(key, {k: out[k] for k in example})
                return cache.rows[key]
        print(f"  {stage} {key}: no valid json after {1 + RETRIES} tries, skipped", file=sys.stderr)
        return None

    def _usage(self, stage: str, usage: Any) -> None:
        price_in, price_out = PRICES[MODEL]
        cost = (usage.prompt_tokens * price_in + usage.completion_tokens * price_out) / 1e6
        self.spent += cost
        self.calls += 1
        row = {
            "stage": stage,
            "model": MODEL,
            "input_tokens": usage.prompt_tokens,
            "output_tokens": usage.completion_tokens,
            "usd": round(cost, 6),
        }
        (OUT / "gen").mkdir(parents=True, exist_ok=True)
        with (OUT / "gen" / "usage.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")


def sample(chunks: list[dict[str, Any]], n: int) -> list[dict[str, Any]]:
    """`n` chunks spread over sections in proportion to their number of eligible chunks."""
    eligible: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for c in chunks:
        if len(c["text"]) >= MIN_CHARS and not c["section_title"].startswith(NO_QUESTIONS_FROM):
            eligible[c["section_path"]].append(c)
    total = sum(len(v) for v in eligible.values())
    rng = random.Random(SEED)
    picked: list[dict[str, Any]] = []
    for path in sorted(eligible):
        group = eligible[path]
        k = max(1, round(n * len(group) / total))
        picked.extend(rng.sample(group, min(k, len(group))))
    rng.shuffle(picked)
    return sorted(picked[:n], key=lambda c: c["ordinal"])


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--n", type=int, default=220, help="chunks to write questions from")
    p.add_argument("--unanswerable", type=int, default=25)
    p.add_argument("--limit", type=int, help="smoke test: only this many chunks, no unanswerable")
    p.add_argument("--budget", type=float, default=float(os.environ.get("BUDGET_USD", "5")))
    args = p.parse_args()

    chunks = [
        json.loads(x) for x in (OUT / "chunks.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    normed = [norm(c["text"]) for c in chunks]
    picked = sample(chunks, args.n)
    if args.limit:
        picked = picked[:: max(1, len(picked) // args.limit)][: args.limit]  # spread over the book
    gen = Generator(args.budget)

    questions: list[dict[str, Any]] = []
    dropped: dict[str, int] = defaultdict(int)
    for c in picked:
        key = f"c{c['ordinal']}"
        asked = gen.run("ask", key, path=c["section_path"], text=c["text"])
        if asked is None:
            dropped["ask_failed"] += 1
            continue
        evidence = norm(asked["evidence"])
        if len(evidence) < 15 or evidence not in normed[c["ordinal"]]:
            dropped["evidence_not_in_chunk"] += 1
            continue
        gold = [i for i, t in enumerate(normed) if evidence in t]
        rewritten = gen.run("rewrite", key, question=asked["question"])
        closed = gen.run("closed", key, question=asked["question"])
        judged = (
            gen.run(
                "judge",
                key,
                question=asked["question"],
                reference=asked["answer"],
                candidate=closed["answer"],
            )
            if closed
            else None
        )
        common = {
            "source_chunk": c["ordinal"],
            "gold_chunks": gold,
            "section_path": c["section_path"],
            "answer": asked["answer"],
            "evidence": asked["evidence"],
            "closed_book_correct": bool(judged and judged["same_fact"]),
            "generator": MODEL,
        }
        questions.append(
            {
                "id": f"{key}-seen",
                "kind": "seen",
                "question": asked["question"],
                "source_id": f"{key}-seen",
                **common,
            }
        )
        if rewritten:
            questions.append(
                {
                    "id": f"{key}-blind",
                    "kind": "blind",
                    "question": rewritten["question"],
                    "source_id": f"{key}-seen",
                    **common,
                }
            )

    if not args.limit:
        paths = sorted(
            {
                c["section_path"]
                for c in chunks
                if not c["section_title"].startswith(NO_QUESTIONS_FROM)
            }
        )
        rng = random.Random(SEED + 1)
        for j, path in enumerate(rng.choices(paths, k=args.unanswerable)):
            out = gen.run("unanswerable", f"u{j}", path=path)
            if out:
                questions.append(
                    {
                        "id": f"u{j}",
                        "kind": "unanswerable",
                        "question": out["question"],
                        "source_id": f"u{j}",
                        "source_chunk": None,
                        "gold_chunks": [],
                        "section_path": path,
                        "generator": MODEL,
                    }
                )

    name = "questions-smoke.jsonl" if args.limit else "questions.jsonl"
    with (OUT / name).open("w", encoding="utf-8") as f:
        for q in questions:
            f.write(json.dumps(q, ensure_ascii=False) + "\n")
    kinds = defaultdict(int)
    for q in questions:
        kinds[q["kind"]] += 1
    closed_ok = sum(q.get("closed_book_correct", False) for q in questions if q["kind"] == "seen")
    print(
        f"{len(picked)} chunks -> {dict(kinds)}; dropped {dict(dropped)}; "
        f"closed-book correct {closed_ok}/{kinds['seen']}"
    )
    print(
        f"{gen.calls} API calls this run, ${gen.spent - gen.spent_before:.4f}; "
        f"all runs ${gen.spent:.4f} at peak prices ({MODEL}) -> {OUT / name}"
    )


if __name__ == "__main__":
    main()
