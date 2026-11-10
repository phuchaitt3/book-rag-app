"""Retrieval latency with and without the reranker, through the app's own retriever (#184).

Runs `book_rag.retrieval.HybridRetriever` over the book's chunks (in memory: bge-m3 from
Ollama for the vector list, a small BM25 for the text list, as bench.py's arm 4), once
without a reranker and once with `TeiReranker` at depth 20, and prints p50/p95 per question
and Hit@1/Hit@5 as a check that the served model behaves like bench.py's arm 5.

Needs Ollama with bge-m3 and a TEI server with BAAI/bge-reranker-v2-m3 (ADR 0009). Compose
does not publish TEI's port, so for this script run one on loopback, for example:
  docker run --rm -p 127.0.0.1:8089:80 -v tei-models:/data \
    ghcr.io/huggingface/text-embeddings-inference:cpu-1.9.4 --model-id BAAI/bge-reranker-v2-m3
Then, from the repository root (DATA_DIR defaults to this folder's git-ignored data/):
  RERANKER_URL=http://127.0.0.1:8089 N=40 uv run python experiments/book-testset/rerank_latency.py
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
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from uuid import UUID, uuid4

from book_rag.providers import OllamaEmbedder, Reranker, TeiReranker
from book_rag.retrieval import HybridRetriever, RetrievedChunk

HERE = Path(__file__).parent
DATA = Path(os.environ.get("DATA_DIR", HERE / "data"))
QUESTIONS = Path(os.environ.get("QUESTIONS", HERE / "questions.jsonl"))
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
RERANKER_URL = os.environ.get("RERANKER_URL", "http://127.0.0.1:8089")
N = int(os.environ.get("N", "40"))
DEPTH = int(os.environ.get("DEPTH", "20"))
WARMUP = 3
SEED = 184
_WORD = re.compile(r"\w+", re.UNICODE)


def tokens(text: str) -> list[str]:
    return [w.lower() for w in _WORD.findall(text)]


class MemorySearcher:
    """The app's two search paths over in-memory chunks: cosine over bge-m3, and BM25."""

    def __init__(self, chunks: list[RetrievedChunk], vectors: list[list[float]]) -> None:
        self.chunks, self.vectors = chunks, vectors
        self.tf = [Counter(tokens(c.text)) for c in chunks]
        self.dl = [sum(t.values()) for t in self.tf]
        self.avgdl = sum(self.dl) / len(self.dl)
        df = Counter(t for tf in self.tf for t in tf)
        n = len(chunks)
        self.idf = {t: math.log(1 + (n - d + 0.5) / (d + 0.5)) for t, d in df.items()}

    async def vector_search(
        self, book_id: UUID, embedding: Sequence[float], limit: int
    ) -> list[RetrievedChunk]:
        sims = [sum(a * b for a, b in zip(v, embedding, strict=True)) for v in self.vectors]
        order = sorted(range(len(sims)), key=lambda i: sims[i], reverse=True)
        return [self.chunks[i] for i in order[:limit]]

    async def text_search(self, book_id: UUID, query: str, limit: int) -> list[RetrievedChunk]:
        k1, b = 1.2, 0.75
        q = Counter(tokens(query))
        scores = []
        for i, tf in enumerate(self.tf):
            norm = k1 * (1 - b + b * self.dl[i] / self.avgdl)
            s = sum(
                c * tf[t] * (k1 + 1) / (tf[t] + norm) * self.idf[t] for t, c in q.items() if t in tf
            )
            scores.append(s)
        order = [i for i in sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)]
        return [self.chunks[i] for i in order[:limit] if scores[i] > 0]


def read_jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f]


def pct(values: list[float], p: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, math.ceil(p * len(ordered)) - 1)]


async def run(
    name: str,
    retriever: HybridRetriever,
    questions: list[dict],
    ordinal: dict[UUID, int],
) -> None:
    for q in questions[:WARMUP]:
        await retriever.retrieve(uuid4(), q["question"], top_k=6)
    times, hit1, hit5 = [], 0, 0
    for q in questions:
        start = time.perf_counter()
        result = await retriever.retrieve(uuid4(), q["question"], top_k=6)
        times.append((time.perf_counter() - start) * 1000)
        ranked = [ordinal[c.id] for c in result]
        hit1 += any(r in q["gold_chunks"] for r in ranked[:1])
        hit5 += any(r in q["gold_chunks"] for r in ranked[:5])
    print(
        f"{name:<22} p50 {statistics.median(times):7.0f} ms  p95 {pct(times, 0.95):7.0f} ms  "
        f"max {max(times):7.0f} ms  Hit@1 {100 * hit1 / len(questions):5.1f}  "
        f"Hit@5 {100 * hit5 / len(questions):5.1f}  (n={len(questions)})"
    )


async def main() -> None:
    rows = read_jsonl(DATA / "chunks.jsonl")
    chunks = [
        RetrievedChunk(id=uuid4(), text=r["text"], page=None, section_path=r["section_path"])
        for r in rows
    ]
    ordinal = {c.id: r["ordinal"] for c, r in zip(chunks, rows, strict=True)}
    embedder = OllamaEmbedder("bge-m3", 1024, OLLAMA_URL)
    vectors: list[list[float]] = []
    for i in range(0, len(chunks), 16):
        vectors += await embedder.embed([c.text for c in chunks[i : i + 16]])
    searcher = MemorySearcher(chunks, vectors)

    pool = [q for q in read_jsonl(QUESTIONS) if q["gold_chunks"]]
    questions = random.Random(SEED).sample(pool, min(N, len(pool)))
    # A long timeout, so a slow server is measured instead of falling back to the fused order.
    reranker: Reranker = TeiReranker(RERANKER_URL, timeout=300)
    print(f"{len(chunks)} chunks, {len(questions)} questions, rerank depth {DEPTH}")
    await run("fused (no reranker)", HybridRetriever(searcher, embedder), questions, ordinal)
    await run(
        f"fused + TEI top {DEPTH}",
        HybridRetriever(searcher, embedder, reranker, rerank_depth=DEPTH),
        questions,
        ordinal,
    )


if __name__ == "__main__":
    asyncio.run(main())
