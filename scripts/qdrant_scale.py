# ruff: noqa: ASYNC240, E501
"""Scale-up arm of the Qdrant experiment (ADR 0008, #115). Delete with the toggle (#120).

SYNTHETIC data: chunks are noisy copies of the 164 real bge-m3 embeddings of one real book, in
books of 1,000 chunks. Queries are noisy copies of real embeddings aimed at one book, so every
search is a filtered search over 1 / (N / 1000) of the collection, as in the app.

    uv run python scripts/qdrant_scale.py real  <real.npy> <pdf>
    uv run python scripts/qdrant_scale.py truth <real.npy> <truth.npz> --chunks 200000
    uv run python scripts/qdrant_scale.py qdrant   <real.npy> <truth.npz> <out.json> --chunks 200000
    uv run python scripts/qdrant_scale.py pgvector <real.npy> <truth.npz> <out.json> --chunks 200000

Run one store at a time (the other container stopped) so a small machine holds one index.
"""

import argparse
import asyncio
import json
import subprocess
import time
import uuid
from pathlib import Path

import numpy as np
from qdrant_client import AsyncQdrantClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from book_rag.chunking import chunk_book
from book_rag.parsing import parse_pdf
from book_rag.providers import OllamaEmbedder
from book_rag_api.models import EMBEDDING_DIM
from book_rag_api.qdrant_index import QdrantVectorIndex
from book_rag_api.retrieval import SqlChunkSearcher

DB = "postgresql+asyncpg://bookrag:bookrag@127.0.0.1:5432/bookrag"
QDRANT = "http://127.0.0.1:6333"
PER_BOOK = 1000
SIGMA = 0.022  # per-dimension noise: the noise vector has norm about 0.7 against a unit base
QUERY_SIGMA = 0.011
QUERIES = 100
LIMIT = 30


def book_uuid(book: int) -> uuid.UUID:
    return uuid.UUID(int=(1 << 100) | (book << 24))


def chunk_uuid(book: int, ordinal: int) -> uuid.UUID:
    return uuid.UUID(int=(2 << 100) | (book << 24) | ordinal)


def book_vectors(real: np.ndarray, book: int) -> np.ndarray:
    """The same 1,000 vectors every time for one book number."""
    rng = np.random.default_rng((12345, book))
    base = real[rng.integers(0, len(real), PER_BOOK)]
    noisy = base + rng.standard_normal(base.shape, dtype=np.float32) * np.float32(SIGMA)
    return (noisy / np.linalg.norm(noisy, axis=1, keepdims=True)).astype(np.float32)


def queries(real: np.ndarray, books: int) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(777)
    target_books = rng.integers(0, books, QUERIES)
    base = real[rng.integers(0, len(real), QUERIES)]
    noisy = base + rng.standard_normal(base.shape, dtype=np.float32) * np.float32(QUERY_SIGMA)
    return target_books, (noisy / np.linalg.norm(noisy, axis=1, keepdims=True)).astype(np.float32)


def percentile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(q * len(ordered)))]


def container_mem(name_part: str) -> str:
    out = subprocess.run(
        ["docker", "stats", "--no-stream", "--format", "{{.Name}} {{.MemUsage}}"],
        capture_output=True,
        text=True,
        check=False,
    ).stdout
    return next((line for line in out.splitlines() if name_part in line), "?")


async def real_embeddings(out: str, pdf: str) -> None:
    parsed = parse_pdf(Path(pdf).read_bytes(), title="book")
    chunks = chunk_book(parsed)
    embedder = OllamaEmbedder("bge-m3", EMBEDDING_DIM, "http://localhost:11434")
    vectors: list[list[float]] = []
    texts = [c.text for c in chunks]
    for start in range(0, len(texts), 16):
        vectors += await embedder.embed(texts[start : start + 16])
    array = np.array(vectors, dtype=np.float32)
    np.save(out, array / np.linalg.norm(array, axis=1, keepdims=True))
    print("real embeddings", array.shape, flush=True)


def truth(real_path: str, out: str, chunks: int) -> None:
    real = np.load(real_path)
    books = chunks // PER_BOOK
    target_books, qvecs = queries(real, books)
    top = np.zeros((QUERIES, LIMIT), dtype=np.int64)
    for i, (book, q) in enumerate(zip(target_books, qvecs, strict=True)):
        scores = book_vectors(real, int(book)) @ q
        top[i] = np.argsort(-scores)[:LIMIT]
    np.savez(out, target_books=target_books, top=top)
    print("truth for", QUERIES, "queries", flush=True)


async def run_rate(search, target_books, qvecs, seconds: float, qps: float) -> tuple[dict, list]:
    latencies: list[float] = []
    results: list = [None] * len(qvecs)
    errors = 0

    async def one(i: int) -> None:
        nonlocal errors
        started = time.perf_counter()
        try:
            results[i % len(qvecs)] = await search(
                int(target_books[i % len(qvecs)]), qvecs[i % len(qvecs)]
            )
        except Exception:
            errors += 1
            return
        latencies.append((time.perf_counter() - started) * 1000)

    tasks = []
    start = time.perf_counter()
    n = 0
    while (now := time.perf_counter() - start) < seconds:
        if now < n / qps:
            await asyncio.sleep(n / qps - now)
        tasks.append(asyncio.create_task(one(n)))
        n += 1
    await asyncio.gather(*tasks)
    return (
        {
            "calls": len(latencies),
            "errors": errors,
            "p50_ms": round(percentile(latencies, 0.5), 1),
            "p95_ms": round(percentile(latencies, 0.95), 1),
            "p99_ms": round(percentile(latencies, 0.99), 1),
        },
        results,
    )


def recall(results: list, top: np.ndarray, target_books: np.ndarray) -> dict:
    scores = []
    for res, truth_row, book in zip(results, top, target_books, strict=True):
        if res is None:
            scores.append(0.0)
            continue
        want = {chunk_uuid(int(book), int(o)) for o in truth_row}
        scores.append(len(want & {r for r in res}) / LIMIT)
    return {"mean": round(float(np.mean(scores)), 4), "min": round(float(np.min(scores)), 4)}


async def qdrant_stage(
    real_path: str, truth_path: str, out: str, chunks: int, seconds: float
) -> None:
    real = np.load(real_path)
    books = chunks // PER_BOOK
    t = np.load(truth_path)
    client = AsyncQdrantClient(url=QDRANT, timeout=120)
    if await client.collection_exists("scale"):
        await client.delete_collection("scale")
    index = QdrantVectorIndex(client, "scale")
    result: dict = {"store": "qdrant", "chunks": chunks, "books": books}
    started = time.perf_counter()
    for book in range(books):
        vecs = book_vectors(real, book)
        await index.upsert(
            book_uuid(book), [(chunk_uuid(book, o), v.tolist()) for o, v in enumerate(vecs)]
        )
        if book % 100 == 0:
            print("loaded books", book, flush=True)
    result["load_s"] = round(time.perf_counter() - started, 1)
    started = time.perf_counter()
    while True:  # wait until the HNSW index covers the points
        info = await client.get_collection("scale")
        if (
            str(info.status).lower().endswith("green")
            and (info.indexed_vectors_count or 0) >= chunks * 0.99
        ):
            break
        await asyncio.sleep(5)
        if time.perf_counter() - started > 3600:
            result["index_timeout"] = True
            break
    result["index_wait_s"] = round(time.perf_counter() - started, 1)
    result["memory"] = container_mem("qdrant")

    async def search(book: int, q: np.ndarray) -> list[uuid.UUID]:
        return await index.search(book_uuid(book), q.tolist(), LIMIT)

    qvecs = queries(real, books)[1]
    _, found = await run_rate(search, t["target_books"], qvecs, 1, 1000)  # warm-up, recall pass
    result["latency"], _ = await run_rate(search, t["target_books"], qvecs, seconds, 5)
    result["recall_at_30"] = recall(found, t["top"], t["target_books"])
    result["memory_after_queries"] = container_mem("qdrant")
    print(json.dumps(result), flush=True)
    Path(out).write_text(json.dumps(result, indent=2), encoding="utf-8")


async def pgvector_stage(
    real_path: str, truth_path: str, out: str, chunks: int, seconds: float
) -> None:
    from pgvector.asyncpg import register_vector

    real = np.load(real_path)
    books = chunks // PER_BOOK
    t = np.load(truth_path)
    dsn = DB.replace("postgresql+asyncpg", "postgresql")
    import asyncpg

    conn = await asyncpg.connect(dsn)
    await register_vector(conn)
    notices: list[str] = []
    conn.add_log_listener(lambda _c, m: notices.append(str(m)))
    result: dict = {"store": "pgvector", "chunks": chunks, "books": books}
    await conn.execute("DROP INDEX IF EXISTS ix_chunks_embedding_hnsw")
    await conn.execute("TRUNCATE books CASCADE")
    await conn.copy_records_to_table(
        "books", columns=["id", "title"], records=[(book_uuid(b), f"b{b}") for b in range(books)]
    )
    started = time.perf_counter()
    for book in range(books):
        vecs = book_vectors(real, book)
        await conn.copy_records_to_table(
            "chunks",
            columns=["id", "book_id", "ordinal", "text", "page", "embedding"],
            records=[
                (chunk_uuid(book, o), book_uuid(book), o, f"chunk {book}-{o}", o, v)
                for o, v in enumerate(vecs)
            ],
        )
        if book % 100 == 0:
            print("loaded books", book, flush=True)
    result["load_s"] = round(time.perf_counter() - started, 1)
    await conn.execute("SET maintenance_work_mem = '2GB'")
    await conn.execute("SET max_parallel_maintenance_workers = 4")
    started = time.perf_counter()
    await conn.execute(
        "CREATE INDEX ix_chunks_embedding_hnsw ON chunks USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64)"
    )
    result["index_build_s"] = round(time.perf_counter() - started, 1)
    result["build_notices"] = notices
    await conn.execute("ANALYZE chunks")
    result["memory"] = container_mem("db-1")
    result["index_size_mb"] = round(
        await conn.fetchval("select pg_relation_size('ix_chunks_embedding_hnsw')") / 1e6
    )
    result["table_size_mb"] = round(await conn.fetchval("select pg_table_size('chunks')") / 1e6)
    await conn.close()

    engine = create_async_engine(DB)
    searcher = SqlChunkSearcher(async_sessionmaker(engine, expire_on_commit=False))

    async def search(book: int, q: np.ndarray) -> list[uuid.UUID]:
        return [c.id for c in await searcher.vector_search(book_uuid(book), q.tolist(), LIMIT)]

    qvecs = queries(real, books)[1]
    _, found = await run_rate(search, t["target_books"], qvecs, 1, 1000)  # warm-up, recall pass
    result["latency"], _ = await run_rate(search, t["target_books"], qvecs, seconds, 5)
    result["recall_at_30"] = recall(found, t["top"], t["target_books"])
    result["memory_after_queries"] = container_mem("db-1")
    print(json.dumps(result), flush=True)
    Path(out).write_text(json.dumps(result, indent=2), encoding="utf-8")
    await engine.dispose()


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("command", choices=["real", "truth", "qdrant", "pgvector"])
    p.add_argument("args", nargs="+")
    p.add_argument("--chunks", type=int, default=200_000)
    p.add_argument("--seconds", type=float, default=60)
    a = p.parse_args()
    if a.command == "real":
        asyncio.run(real_embeddings(a.args[0], a.args[1]))
    elif a.command == "truth":
        truth(a.args[0], a.args[1], a.chunks)
    elif a.command == "qdrant":
        asyncio.run(qdrant_stage(a.args[0], a.args[1], a.args[2], a.chunks, a.seconds))
    else:
        asyncio.run(pgvector_stage(a.args[0], a.args[1], a.args[2], a.chunks, a.seconds))


if __name__ == "__main__":
    main()
