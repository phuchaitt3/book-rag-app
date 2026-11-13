"""Does an accent-insensitive keyword leg change the results on the Vietnamese book? (#95)

Measurement only. Loads the book's 359 chunks into a throwaway pgvector Postgres container
(no GPU, no embeddings) and compares the keyword leg for:

  A  today: to_tsvector('simple', text), query to_tsquery('simple', ...)
  B  the same with unaccent applied to the text and to the query (a second tsvector column)

Each arm is scored two ways:
  ts_rank_cd  the SQL leg of the app before ADR 0011 (OR query), with latency per query
  bm25        BM25 (k1 1.2, b 0.75) in Python over the same tokens (the ranking ceiling; the
              shipped BM25 leg ranks the same tokens), with unaccented tokens for B

and on two query sets: the questions as written (accented) and the same questions with every
accent removed (users often type without them). Questions: the 416 answerable ones (208 `seen`,
208 `blind`); a hit is a chunk in the top k that contains the question's evidence sentence,
as gap.py scores. The fused (dense + keyword) result is not computed: it needs Ollama embeddings
of the chunks, and this run uses no model.

Run from the repository root (needs Docker; no GPU):
  BOOK_DATA=<main checkout>/experiments/book-testset/data \\
  python ~/claude-config/scripts/gpu_run.py run --resource ram --wait -- \\
    uv run python experiments/e2e/fts_unaccent.py
Writes experiments/e2e/results/fts-unaccent-95.json.
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import random
import re
import statistics
import time
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any

import asyncpg  # type: ignore[import-untyped]
from testcontainers.community.postgres import PostgresContainer

ROOT = Path(__file__).parents[2]
DATA = Path(os.environ.get("BOOK_DATA", ROOT / "experiments" / "book-testset" / "data"))
QUESTIONS = ROOT / "experiments" / "book-testset" / "questions.jsonl"
OUT = Path(__file__).parent / "results" / "fts-unaccent-95.json"
CONTAINER = "book-rag-95-pg"
IMAGE = "pgvector/pgvector:pg17"
CANDIDATES, K1, B = 30, 1.2, 0.75
WORD = re.compile(r"\w+", re.UNICODE)
_NOISE = re.compile(r"[\W_\d]+", re.UNICODE)  # as retrieval_check.norm, without the CJK ranges


def norm(text: str) -> str:
    """Lowercase NFC letters only, so punctuation and spacing do not hide an evidence match."""
    return _NOISE.sub("", unicodedata.normalize("NFC", text).lower())


def strip_accents(text: str) -> str:
    """Python-side accent removal, only to build the 'typed without accents' query set."""
    d = unicodedata.normalize("NFD", text)
    d = "".join(c for c in d if unicodedata.category(c) != "Mn")
    return d.replace("đ", "d").replace("Đ", "D")


def or_query(query: str) -> str:  # copy of book_rag_api.retrieval.or_query
    return " | ".join(WORD.findall(query))


def interval(hits: list[int], seed: int = 95, reps: int = 5000) -> list[float]:
    rng = random.Random(seed)
    n = len(hits)
    means = sorted(sum(hits[rng.randrange(n)] for _ in range(n)) / n for _ in range(reps))
    return [round(100 * means[int(0.025 * reps)], 1), round(100 * means[int(0.975 * reps)], 1)]


def score(ranks: list[list[int]], gold: list[set[int]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k in (1, 5):
        hits = [int(bool(set(r[:k]) & g)) for r, g in zip(ranks, gold, strict=True)]
        out[f"hit@{k}"] = round(100 * sum(hits) / len(hits), 1)
        out[f"hit@{k}_ci95"] = interval(hits)
    return out


def lat(times: list[float]) -> dict[str, float]:
    s = sorted(times)
    return {"median_ms": round(statistics.median(s), 2), "p95_ms": round(s[int(0.95 * len(s))], 2)}


class Bm25:
    def __init__(self, docs: list[list[str]]) -> None:
        self.tf = [Counter(d) for d in docs]
        self.dl = [len(d) for d in docs]
        self.avg = sum(self.dl) / len(docs)
        df: Counter[str] = Counter(t for c in self.tf for t in c)
        n = len(docs)
        self.idf = {t: math.log(1 + (n - c + 0.5) / (c + 0.5)) for t, c in df.items()}

    def top(self, query: list[str], n: int) -> list[int]:
        qtf = Counter(t for t in query if t in self.idf)
        scores = []
        for i, c in enumerate(self.tf):
            s = sum(
                q
                * self.idf[t]
                * c[t]
                * (K1 + 1)
                / (c[t] + K1 * (1 - B + B * self.dl[i] / self.avg))
                for t, q in qtf.items()
                if t in c
            )
            if s > 0:
                scores.append((s, i))
        scores.sort(key=lambda p: -p[0])
        return [i for _, i in scores[:n]]


async def sql_leg(
    conn: Any, col: str, queries: list[str], unaccent_query: bool
) -> tuple[list[list[int]], list[float]]:
    """ts_rank_cd over an OR query on column `col`; for B the query goes through unaccent()."""
    qx = "unaccent($1)" if unaccent_query else "$1"
    sql = (
        f"SELECT ordinal FROM chunks WHERE {col} @@ to_tsquery('simple', {qx}) "
        f"ORDER BY ts_rank_cd({col}, to_tsquery('simple', {qx})) DESC LIMIT {CANDIDATES}"
    )
    out, times = [], []
    for q in queries:
        tsq = or_query(q)
        t0 = time.perf_counter()
        rows = await conn.fetch(sql, tsq) if tsq else []
        times.append((time.perf_counter() - t0) * 1000)
        out.append([r["ordinal"] for r in rows])
    return out, times


async def run(conn: Any) -> dict[str, Any]:
    chunks = [json.loads(x) for x in (DATA / "chunks.jsonl").read_text("utf-8").splitlines()]
    qs = [json.loads(x) for x in QUESTIONS.read_text("utf-8").splitlines() if x.strip()]
    qs = [q for q in qs if q["kind"] in ("seen", "blind")]
    texts = [c["text"] for c in chunks]
    normed = [norm(t) for t in texts]
    gold = [{i for i, t in enumerate(normed) if norm(q["evidence"]) in t} for q in qs]
    assert all(gold), "every question needs evidence in one chunk"

    await conn.execute("CREATE EXTENSION IF NOT EXISTS unaccent")
    await conn.execute(
        "CREATE TABLE chunks (ordinal int PRIMARY KEY, text text, "
        "tsv tsvector GENERATED ALWAYS AS (to_tsvector('simple', text)) STORED, tsv_u tsvector)"
    )
    await conn.executemany(
        "INSERT INTO chunks (ordinal, text) VALUES ($1, $2)", list(enumerate(texts))
    )
    # unaccent() is STABLE, so the second column is filled once here; the app would wrap it in
    # an IMMUTABLE function for a generated column or an expression index.
    await conn.execute("UPDATE chunks SET tsv_u = to_tsvector('simple', unaccent(text))")
    await conn.execute("CREATE INDEX chunks_tsv_idx ON chunks USING gin (tsv)")
    await conn.execute("CREATE INDEX chunks_tsv_u_idx ON chunks USING gin (tsv_u)")
    await conn.execute("ANALYZE chunks")
    probe = await conn.fetchval("SELECT unaccent('Việt Đức học sinh Hà Nội, ươ ế')")
    sizes = await conn.fetchrow(
        "SELECT pg_relation_size('chunks_tsv_idx') a, pg_relation_size('chunks_tsv_u_idx') b"
    )
    print("unaccent probe:", probe)

    # the same tokenisation as the `simple` configuration, taken from Postgres itself
    async def lexemes(expr: str) -> list[list[str]]:
        rows = await conn.fetch(
            f"SELECT array(SELECT l FROM ts_debug('simple', {expr}) d, unnest(d.lexemes) l "
            ") AS t FROM chunks ORDER BY ordinal"
        )
        return [list(r["t"]) for r in rows]

    bm_a, bm_b = Bm25(await lexemes("text")), Bm25(await lexemes("unaccent(text)"))

    report: dict[str, Any] = {
        "chunks": len(texts),
        "questions": len(qs),
        "unaccent_probe": probe,
        "gin_index_bytes": {"tsv": sizes["a"], "tsv_unaccent": sizes["b"]},
        "query_sets": {},
    }
    kinds = [q["kind"] for q in qs]
    for set_name, queries in (
        ("accented", [q["question"] for q in qs]),
        ("stripped", [strip_accents(q["question"]) for q in qs]),
    ):
        arms: dict[str, list[list[int]]] = {}
        timing: dict[str, Any] = {}
        arms["A ts_rank_cd"], t = await sql_leg(conn, "tsv", queries, False)
        timing["A ts_rank_cd"] = lat(t)
        arms["B ts_rank_cd"], t = await sql_leg(conn, "tsv_u", queries, True)
        timing["B ts_rank_cd"] = lat(t)
        arms["A bm25"] = [
            bm_a.top([w.lower() for w in WORD.findall(q)], CANDIDATES) for q in queries
        ]
        un_q = [await conn.fetchval("SELECT unaccent($1)", q) for q in queries]
        arms["B bm25"] = [bm_b.top([w.lower() for w in WORD.findall(q)], CANDIDATES) for q in un_q]
        res: dict[str, Any] = {}
        for arm, ranks in arms.items():
            block = {"all": score(ranks, gold)}
            for kind in ("seen", "blind"):
                idx = [i for i, k in enumerate(kinds) if k == kind]
                block[kind] = score([ranks[i] for i in idx], [gold[i] for i in idx])
            res[arm] = block
            m = block["all"]
            print(
                f"{set_name:9s} {arm:14s} Hit@1 {m['hit@1']:5.1f}  Hit@5 {m['hit@5']:5.1f} "
                f"{m['hit@5_ci95']}  seen {block['seen']['hit@5']:5.1f} "
                f"blind {block['blind']['hit@5']:5.1f}  {timing.get(arm, '')}"
            )
        a5 = [int(bool(set(r[:5]) & g)) for r, g in zip(arms["A ts_rank_cd"], gold, strict=True)]
        b5 = [int(bool(set(r[:5]) & g)) for r, g in zip(arms["B ts_rank_cd"], gold, strict=True)]
        report["query_sets"][set_name] = {
            "arms": res,
            "latency": timing,
            "ts_rank_cd_hit@5_B_only": sum(b > a for a, b in zip(a5, b5, strict=True)),
            "ts_rank_cd_hit@5_A_only": sum(a > b for a, b in zip(a5, b5, strict=True)),
            "queries_with_no_match": {
                arm: sum(1 for r in ranks if not r) for arm, ranks in arms.items()
            },
        }
    return report


async def main() -> None:
    container = PostgresContainer(IMAGE, driver=None).with_name(CONTAINER)
    container.with_kwargs(mem_limit="1g", shm_size="128m")
    try:
        container.start()
        conn = await asyncpg.connect(
            host=container.get_container_host_ip(),
            port=int(container.get_exposed_port(5432)),
            user=container.username,
            password=container.password,
            database=container.dbname,
        )
        try:
            report = await run(conn)
        finally:
            await conn.close()
    finally:
        container.stop()
    OUT.write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(main())
