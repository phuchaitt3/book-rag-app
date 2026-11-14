"""Does unaccent still help once the keyword leg is fused with the dense leg? (#95)

Sibling of fts_unaccent.py (same book, questions, gold rule, accented and stripped query sets,
same Postgres container, same two keyword columns). Adds the dense leg: Ollama bge-m3
embeddings of the chunks and of each query, exact cosine in numpy (the app's HNSW search with
strict_order returns the same order), and the app's fusion, RRF with k 60 over 30 candidates
per leg (book_rag.retrieval.fusion). The dense leg is identical in both arms (a stripped query
is embedded as stripped); only the keyword leg differs: A `simple`, B `unaccent`.

Run from the repository root (needs Docker and Ollama at 127.0.0.1:11434):
  BOOK_DATA=<main checkout>/experiments/book-testset/data \
  python ~/claude-config/scripts/gpu_run.py run --wait -- \
    uv run python experiments/e2e/fts_unaccent_fused.py
Writes experiments/e2e/results/fts-unaccent-fused-95.json.
"""

from __future__ import annotations

import asyncio
import json
import os
import urllib.request
from typing import Any

import asyncpg  # type: ignore[import-untyped]
import fts_unaccent as fu
import numpy as np
from testcontainers.community.postgres import PostgresContainer

OLLAMA = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
OUT = fu.Path(__file__).parent / "results" / "fts-unaccent-fused-95.json"
RRF_K = 60


def embed(texts: list[str], batch: int = 16) -> np.ndarray:
    vectors: list[list[float]] = []
    for i in range(0, len(texts), batch):
        body = json.dumps({"model": "bge-m3", "input": texts[i : i + batch]}).encode()
        req = urllib.request.Request(
            f"{OLLAMA}/api/embed", data=body, headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=600) as r:
            vectors += json.loads(r.read())["embeddings"]
    m = np.asarray(vectors, dtype=np.float32)
    return m / np.linalg.norm(m, axis=1, keepdims=True)


def rrf(rankings: list[list[int]]) -> list[int]:  # book_rag.retrieval.fusion
    scores: dict[int, float] = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking, start=1):
            scores[item] = scores.get(item, 0.0) + 1.0 / (RRF_K + rank)
    return [i for i, _ in sorted(scores.items(), key=lambda p: p[1], reverse=True)]


async def run(conn: Any) -> dict[str, Any]:
    chunks = [json.loads(x) for x in (fu.DATA / "chunks.jsonl").read_text("utf-8").splitlines()]
    qs = [json.loads(x) for x in fu.QUESTIONS.read_text("utf-8").splitlines() if x.strip()]
    qs = [q for q in qs if q["kind"] in ("seen", "blind")]
    texts = [c["text"] for c in chunks]
    normed = [fu.norm(t) for t in texts]
    gold = [{i for i, t in enumerate(normed) if fu.norm(q["evidence"]) in t} for q in qs]
    assert all(gold), "every question needs evidence in one chunk"

    await conn.execute("CREATE EXTENSION IF NOT EXISTS unaccent")
    await conn.execute(
        "CREATE TABLE chunks (ordinal int PRIMARY KEY, text text, "
        "tsv tsvector GENERATED ALWAYS AS (to_tsvector('simple', text)) STORED, tsv_u tsvector)"
    )
    await conn.executemany(
        "INSERT INTO chunks (ordinal, text) VALUES ($1, $2)", list(enumerate(texts))
    )
    await conn.execute("UPDATE chunks SET tsv_u = to_tsvector('simple', unaccent(text))")
    await conn.execute("CREATE INDEX chunks_tsv_idx ON chunks USING gin (tsv)")
    await conn.execute("CREATE INDEX chunks_tsv_u_idx ON chunks USING gin (tsv_u)")
    await conn.execute("ANALYZE chunks")

    async def lexemes(expr: str) -> list[list[str]]:
        rows = await conn.fetch(
            f"SELECT array(SELECT l FROM ts_debug('simple', {expr}) d, unnest(d.lexemes) l "
            ") AS t FROM chunks ORDER BY ordinal"
        )
        return [list(r["t"]) for r in rows]

    bm_a, bm_b = fu.Bm25(await lexemes("text")), fu.Bm25(await lexemes("unaccent(text)"))
    cvec = embed(texts)
    kinds = [q["kind"] for q in qs]
    report: dict[str, Any] = {"chunks": len(texts), "questions": len(qs), "query_sets": {}}
    for set_name, queries in (
        ("accented", [q["question"] for q in qs]),
        ("stripped", [fu.strip_accents(q["question"]) for q in qs]),
    ):
        qvec = embed(queries)
        dense = [
            [int(i) for i in np.argsort(-row, kind="stable")[: fu.CANDIDATES]]
            for row in qvec @ cvec.T
        ]
        keyword: dict[str, list[list[int]]] = {}
        keyword["A ts_rank_cd"], _ = await fu.sql_leg(conn, "tsv", queries, False)
        keyword["B ts_rank_cd"], _ = await fu.sql_leg(conn, "tsv_u", queries, True)
        keyword["A bm25"] = [
            bm_a.top([w.lower() for w in fu.WORD.findall(q)], fu.CANDIDATES) for q in queries
        ]
        un_q = [await conn.fetchval("SELECT unaccent($1)", q) for q in queries]
        keyword["B bm25"] = [
            bm_b.top([w.lower() for w in fu.WORD.findall(q)], fu.CANDIDATES) for q in un_q
        ]
        arms: dict[str, list[list[int]]] = {"dense only": dense}
        for name, leg in keyword.items():
            arms[f"{name} alone"] = leg
            arms[f"{name} + dense"] = [rrf([d, k]) for d, k in zip(dense, leg, strict=True)]
        res: dict[str, Any] = {}
        for arm, ranks in arms.items():
            block = {"all": fu.score(ranks, gold)}
            for kind in ("seen", "blind"):
                idx = [i for i, k in enumerate(kinds) if k == kind]
                block[kind] = fu.score([ranks[i] for i in idx], [gold[i] for i in idx])
            res[arm] = block
            m = block["all"]
            print(
                f"{set_name:9s} {arm:20s} Hit@1 {m['hit@1']:5.1f}  Hit@5 {m['hit@5']:5.1f} "
                f"{m['hit@5_ci95']}  seen {block['seen']['hit@5']:5.1f} "
                f"blind {block['blind']['hit@5']:5.1f}"
            )
        for leg in ("ts_rank_cd", "bm25"):
            a5 = [
                int(bool(set(r[:5]) & g))
                for r, g in zip(arms[f"A {leg} + dense"], gold, strict=True)
            ]
            b5 = [
                int(bool(set(r[:5]) & g))
                for r, g in zip(arms[f"B {leg} + dense"], gold, strict=True)
            ]
            res[f"fused {leg} Hit@5 B-only / A-only"] = [
                sum(b > a for a, b in zip(a5, b5, strict=True)),
                sum(a > b for a, b in zip(a5, b5, strict=True)),
            ]
        report["query_sets"][set_name] = res
    return report


async def main() -> None:
    container = PostgresContainer(fu.IMAGE, driver=None).with_name("book-rag-95-fused-pg")
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
