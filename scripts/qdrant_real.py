"""Real-embedding run of the Qdrant experiment (ADR 0008, #115). Delete with the toggle (#120).

Embeds the book test set's chunks and questions with bge-m3 (Ollama), loads the same vectors into
pgvector (HNSW) and Qdrant, and reports per exit criterion: recall@30 against the exact scan,
overlap@30 between the stores, Hit@k against the gold chunks, p50/p95/p99 latency at one rate,
index build and load time, Qdrant memory and count drift. Needs a Postgres with pgvector on
127.0.0.1:5432 (container bra115real-pg), Qdrant on 127.0.0.1:6333 (bra115real-qdrant) and Ollama
with bge-m3 on 127.0.0.1:11434.

    uv run python scripts/qdrant_real.py <data_dir> <questions.jsonl> <out.json> [--seconds 300]
"""

import argparse
import asyncio
import json
import statistics
import subprocess
import time
import uuid
from pathlib import Path

from qdrant_experiment import DB, LIMIT, exact_top, make_index, run_rate
from sqlalchemy import insert, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from book_rag.providers import OllamaEmbedder
from book_rag_api.models import EMBEDDING_DIM, Base, Book, Chunk
from book_rag_api.qdrant_index import QdrantChunkSearcher, vector_counts
from book_rag_api.retrieval import SqlChunkSearcher

KS = (1, 5, 10, 30)


async def embed_all(texts: list[str]) -> list[list[float]]:
    embedder = OllamaEmbedder("bge-m3", EMBEDDING_DIM, "http://127.0.0.1:11434")
    vectors: list[list[float]] = []
    for start in range(0, len(texts), 16):
        vectors += await embedder.embed(texts[start : start + 16])
    return vectors


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()]


def write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def container_mem(name: str) -> str:
    out = subprocess.run(
        ["docker", "stats", "--no-stream", "--format", "{{.Name}} {{.MemUsage}}", name],
        capture_output=True,
        text=True,
        check=False,
    ).stdout
    return out.strip()


def hit_rates(ranked: list[list[int]], gold: list[set[int]]) -> dict[str, float]:
    return {
        f"hit@{k}": round(
            sum(1 for r, g in zip(ranked, gold, strict=True) if g & set(r[:k])) / len(gold), 4
        )
        for k in KS
    }


async def main(data: str, questions_path: str, out: str, seconds: float, qps: float) -> None:
    chunks = read_jsonl(Path(data, "chunks.jsonl"))
    rows = [q for q in read_jsonl(Path(questions_path)) if q["kind"] != "unanswerable"]
    result: dict = {"chunks": len(chunks), "queries_total": len(rows)}

    started = time.perf_counter()
    chunk_vectors = await embed_all([c["text"] for c in chunks])
    result["embed_chunks_seconds"] = round(time.perf_counter() - started, 1)
    started = time.perf_counter()
    query_vectors = await embed_all([q["question"] for q in rows])
    result["embed_queries_seconds"] = round(time.perf_counter() - started, 1)
    print(result, flush=True)

    engine = create_async_engine(DB, pool_size=20)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text("DROP INDEX ix_chunks_embedding_hnsw"))
    book_id = uuid.uuid4()
    ids = [uuid.uuid4() for _ in chunks]
    started = time.perf_counter()
    async with sessions.begin() as s:
        s.add(Book(id=book_id, title=chunks[0]["book_title"]))
        await s.flush()
        await s.execute(
            insert(Chunk),
            [
                {
                    "id": i,
                    "book_id": book_id,
                    "ordinal": c["ordinal"],
                    "text": c["text"],
                    "section_path": c.get("section_path"),
                    "embedding": v,
                }
                for i, c, v in zip(ids, chunks, chunk_vectors, strict=True)
            ],
        )
    result["pgvector_load_seconds"] = round(time.perf_counter() - started, 2)
    started = time.perf_counter()
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "CREATE INDEX ix_chunks_embedding_hnsw ON chunks USING hnsw "
                "(embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64)"
            )
        )
    result["pgvector_hnsw_build_seconds"] = round(time.perf_counter() - started, 2)
    async with engine.connect() as conn:
        await conn.execution_options(isolation_level="AUTOCOMMIT")
        await conn.execute(text("ANALYZE chunks"))

    index = make_index("real115")
    started = time.perf_counter()
    await index.upsert(book_id, list(zip(ids, chunk_vectors, strict=True)))
    result["qdrant_load_seconds"] = round(time.perf_counter() - started, 2)
    result["qdrant_memory"] = container_mem("bra115real-qdrant")
    result["postgres_memory"] = container_mem("bra115real-pg")
    pg, qd = await vector_counts(sessions, index, book_id)
    result["count_drift"] = {"postgres": pg, "qdrant": qd}

    sql = SqlChunkSearcher(sessions)
    qdrant = QdrantChunkSearcher(index, sessions, sql)
    ordinal_of = {i: c["ordinal"] for i, c in zip(ids, chunks, strict=True)}
    ranked: dict[str, list[list[int]]] = {"pgvector": [], "qdrant": [], "exact": []}
    recalls: dict[str, list[float]] = {"pgvector": [], "qdrant": []}
    overlaps: list[float] = []
    for v in query_vectors:
        exact = await exact_top(sessions, book_id, v)
        pg_ids = [c.id for c in await sql.vector_search(book_id, v, LIMIT)]
        qd_ids = [c.id for c in await qdrant.vector_search(book_id, v, LIMIT)]
        for name, found in (("exact", exact), ("pgvector", pg_ids), ("qdrant", qd_ids)):
            ranked[name].append([ordinal_of[i] for i in found])
        recalls["pgvector"].append(len(set(exact) & set(pg_ids)) / len(exact))
        recalls["qdrant"].append(len(set(exact) & set(qd_ids)) / len(exact))
        overlaps.append(len(set(pg_ids) & set(qd_ids)) / max(1, len(pg_ids)))
    result["recall_at_30_vs_exact"] = {
        k: {"mean": round(statistics.fmean(r), 4), "min": round(min(r), 4)}
        for k, r in recalls.items()
    }
    result["overlap_at_30_pgvector_vs_qdrant"] = {
        "mean": round(statistics.fmean(overlaps), 4),
        "min": round(min(overlaps), 4),
        "share_identical": round(sum(1 for o in overlaps if o == 1.0) / len(overlaps), 4),
    }
    result["hit_rates"] = {}
    for kind in ("seen", "blind"):
        pick = [i for i, q in enumerate(rows) if q["kind"] == kind]
        gold = [set(rows[i]["gold_chunks"]) for i in pick]
        result["hit_rates"][kind] = {
            "queries": len(pick),
            **{name: hit_rates([r[i] for i in pick], gold) for name, r in ranked.items()},
        }
    print(json.dumps(result, indent=1), flush=True)

    result["latency"] = {}
    for name, searcher in (("pgvector", sql), ("qdrant", qdrant)):
        result["latency"][name] = await run_rate(searcher, book_id, query_vectors, seconds, qps)
        print(name, result["latency"][name], flush=True)
    result["qdrant_memory_after_load_test"] = container_mem("bra115real-qdrant")
    write_json(Path(out), result)
    await index.close()
    await engine.dispose()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("data")
    p.add_argument("questions")
    p.add_argument("out")
    p.add_argument("--seconds", type=float, default=300)
    p.add_argument("--qps", type=float, default=5)
    a = p.parse_args()
    asyncio.run(main(a.data, a.questions, a.out, a.seconds, a.qps))
