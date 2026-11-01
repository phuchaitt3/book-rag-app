"""Measurements for the Qdrant experiment (ADR 0008, #115). Delete with the toggle (#120).

Needs the Compose db and qdrant services reachable on localhost and Ollama with bge-m3.

    uv run python scripts/qdrant_experiment.py ingest  <pdf> <results.json>
    uv run python scripts/qdrant_experiment.py measure <results.json> [--seconds 300 --qps 5]
    uv run python scripts/qdrant_experiment.py copies  <results.json> --books 100 [--seconds 60]
"""

import argparse
import asyncio
import json
import random
import statistics
import time
import uuid
from pathlib import Path

from qdrant_client import AsyncQdrantClient
from sqlalchemy import delete, func, insert, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from book_rag.providers import OllamaEmbedder
from book_rag.retrieval import RetrievedChunk
from book_rag_api.models import EMBEDDING_DIM, Book, Chunk, IngestionJob
from book_rag_api.qdrant_index import QdrantChunkSearcher, QdrantVectorIndex, vector_counts
from book_rag_api.retrieval import SqlChunkSearcher
from book_rag_worker.ingest import run_ingestion

DB = "postgresql+asyncpg://bookrag:bookrag@127.0.0.1:5432/bookrag"
QDRANT = "http://127.0.0.1:6333"
LIMIT = 30


def make_index(collection: str = "chunks") -> QdrantVectorIndex:
    return QdrantVectorIndex(AsyncQdrantClient(url=QDRANT, timeout=60), collection)


def load(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save(path: str, data: dict) -> None:
    Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def percentile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(q * len(ordered)))]


def summarise(latencies: list[float], seconds: float) -> dict:
    return {
        "calls": len(latencies),
        "achieved_qps": round(len(latencies) / seconds, 2),
        "p50_ms": round(percentile(latencies, 0.50), 2),
        "p95_ms": round(percentile(latencies, 0.95), 2),
        "p99_ms": round(percentile(latencies, 0.99), 2),
        "mean_ms": round(statistics.fmean(latencies), 2),
    }


async def ingest(pdf: str, out: str) -> None:
    engine = create_async_engine(DB)
    sessions = async_sessionmaker(engine)
    embedder = OllamaEmbedder("bge-m3", EMBEDDING_DIM, "http://localhost:11434")
    index = make_index()
    data = await asyncio.to_thread(Path(pdf).read_bytes)
    async with sessions.begin() as s:
        book = Book(title="Tat den (experiment)", storage_key="book.pdf")
        s.add(book)
        await s.flush()
        book_id = book.id
    runs = []
    for attempt in (1, 2):  # the second run is the retried ingestion: ids are replaced
        async with sessions.begin() as s:
            job = IngestionJob(book_id=book_id)
            s.add(job)
            await s.flush()
            job_id = job.id
        started = time.perf_counter()
        await run_ingestion(engine, job_id, lambda _key: data, embedder, 32, index=index)
        seconds = time.perf_counter() - started
        async with sessions() as s:
            status = await s.scalar(select(IngestionJob.status).where(IngestionJob.id == job_id))
        pg, qd = await vector_counts(sessions, index, book_id)
        runs.append(
            {
                "attempt": attempt,
                "status": status,
                "seconds": round(seconds, 1),
                "postgres": pg,
                "qdrant": qd,
            }
        )
        print(runs[-1], flush=True)
    save(out, {"book_id": str(book_id), "ingestion_runs": runs})
    await engine.dispose()


def passage(text_: str) -> str:
    """A question-sized piece of a chunk: its longest sentence among the first three."""
    sentences = [p.strip() for p in text_.replace("\n", " ").split(". ") if len(p.strip()) > 30]
    return max(sentences[:3], key=len) if sentences else text_[:200]


async def exact_top(sessions, book_id: uuid.UUID, vector: list[float]) -> list[uuid.UUID]:
    """The true nearest chunks: a sequential scan with every index switched off."""
    async with sessions() as s:
        await s.execute(text("SET LOCAL enable_indexscan = off"))
        await s.execute(text("SET LOCAL enable_bitmapscan = off"))
        rows = await s.scalars(
            select(Chunk.id)
            .where(Chunk.book_id == book_id, Chunk.embedding.is_not(None))
            .order_by(Chunk.embedding.cosine_distance(vector))
            .limit(LIMIT)
        )
        return list(rows)


async def run_rate(searcher, book_id, vectors, seconds: float, qps: float) -> dict:
    latencies: list[float] = []
    errors = 0

    async def one(vector: list[float]) -> None:
        nonlocal errors
        started = time.perf_counter()
        try:
            await searcher.vector_search(book_id, vector, LIMIT)
        except Exception:
            errors += 1
            return
        latencies.append((time.perf_counter() - started) * 1000)

    tasks: list[asyncio.Task] = []
    start = time.perf_counter()
    n = 0
    while (now := time.perf_counter() - start) < seconds:
        due = n / qps
        if now < due:
            await asyncio.sleep(due - now)
        tasks.append(asyncio.create_task(one(vectors[n % len(vectors)])))
        n += 1
    await asyncio.gather(*tasks)
    result = summarise(latencies, time.perf_counter() - start)
    result["errors"] = errors
    result["target_qps"] = qps
    return result


async def measure_book(out: str, seconds: float, qps: float, book_key: str, label: str) -> None:
    data = load(out)
    book_id = uuid.UUID(data[book_key])
    engine = create_async_engine(DB, pool_size=20)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    index = make_index()
    sql = SqlChunkSearcher(sessions)
    qdrant = QdrantChunkSearcher(index, sessions, sql)
    embedder = OllamaEmbedder("bge-m3", EMBEDDING_DIM, "http://localhost:11434")

    async with sessions() as s:
        texts = list(await s.scalars(select(Chunk.text).where(Chunk.book_id == book_id)))
        total = await s.scalar(select(func.count()).select_from(Chunk))
    rng = random.Random(0)
    questions = [passage(t) for t in rng.sample(texts, min(120, len(texts)))]
    vectors = []
    for start in range(0, len(questions), 16):
        vectors += await embedder.embed(questions[start : start + 16])

    recalls = {"pgvector": [], "qdrant": []}
    for v in vectors:
        exact = set(await exact_top(sessions, book_id, v))
        for name, searcher in (("pgvector", sql), ("qdrant", qdrant)):
            found: list[RetrievedChunk] = await searcher.vector_search(book_id, v, LIMIT)
            recalls[name].append(len(exact & {c.id for c in found}) / max(1, len(exact)))
    result = {
        "label": label,
        "chunks_in_database": total,
        "chunks_in_book": len(texts),
        "questions": len(vectors),
        "recall_at_30_mean": {k: round(statistics.fmean(r), 4) for k, r in recalls.items()},
        "recall_at_30_min": {k: round(min(r), 4) for k, r in recalls.items()},
    }
    print(result, flush=True)
    for name, searcher in (("pgvector", sql), ("qdrant", qdrant)):
        result[f"latency_{name}"] = await run_rate(searcher, book_id, vectors, seconds, qps)
        print(name, result[f"latency_{name}"], flush=True)
    data.setdefault("measurements", []).append(result)
    save(out, data)
    await engine.dispose()


async def consistency(out: str) -> None:
    """Delete the book in Postgres and in Qdrant; both counts must reach zero."""
    data = load(out)
    book_id = uuid.UUID(data["book_id"])
    engine = create_async_engine(DB)
    sessions = async_sessionmaker(engine)
    index = make_index()
    before = await vector_counts(sessions, index, book_id)
    await index.delete_book(book_id)
    async with sessions.begin() as s:
        await s.execute(delete(Book).where(Book.id == book_id))
    after = await vector_counts(sessions, index, book_id)
    data["deletion"] = {"before": before, "after": after}
    print(data["deletion"])
    save(out, data)
    await engine.dispose()


async def copies(out: str, books: int, seconds: float, qps: float) -> None:
    """Copy the book's chunks (with their real embeddings) into `books - 1` more books."""
    data = load(out)
    source = uuid.UUID(data["book_id"])
    engine = create_async_engine(DB)
    sessions = async_sessionmaker(engine)
    index = make_index()
    async with sessions() as s:
        rows = list(
            (
                await s.execute(
                    select(
                        Chunk.ordinal, Chunk.text, Chunk.page, Chunk.section_path, Chunk.embedding
                    ).where(Chunk.book_id == source)
                )
            ).all()
        )
    for n in range(books - 1):
        new_id = uuid.uuid4()
        async with sessions.begin() as s:
            s.add(Book(id=new_id, title=f"copy {n}"))
            await s.flush()
            ids = [uuid.uuid4() for _ in rows]
            await s.execute(
                insert(Chunk),
                [
                    {
                        "id": i,
                        "book_id": new_id,
                        "ordinal": r.ordinal,
                        "text": r.text,
                        "page": r.page,
                        "section_path": r.section_path,
                        "embedding": r.embedding,
                    }
                    for i, r in zip(ids, rows, strict=True)
                ],
            )
        await index.upsert(new_id, [(i, r.embedding) for i, r in zip(ids, rows, strict=True)])
    await engine.dispose()
    print(f"copied into {books - 1} more books", flush=True)
    await measure_book(out, seconds, qps, "book_id", f"{books} books (copies of one book)")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("command", choices=["ingest", "measure", "consistency", "copies"])
    p.add_argument("args", nargs="+")
    p.add_argument("--seconds", type=float, default=300)
    p.add_argument("--qps", type=float, default=5)
    p.add_argument("--books", type=int, default=100)
    a = p.parse_args()
    if a.command == "ingest":
        asyncio.run(ingest(a.args[0], a.args[1]))
    elif a.command == "measure":
        asyncio.run(measure_book(a.args[0], a.seconds, a.qps, "book_id", "1 real book"))
    elif a.command == "consistency":
        asyncio.run(consistency(a.args[0]))
    else:
        asyncio.run(copies(a.args[0], a.books, a.seconds, a.qps))


if __name__ == "__main__":
    main()
