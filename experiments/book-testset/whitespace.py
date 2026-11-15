"""Does collapsed whitespace hurt retrieval? (#152) Pre-registered in docs/benchmarks/whitespace.md.

Three corpus variants of the same book, identical except whitespace, scored with arm 4 of
bench.py (bge-m3 + BM25, RRF k=60, no reranker) on the checked questions (seen and blind):
  A   every page's text with whitespace collapsed (the app's form; checked equal to the corpus
      of #177 in OUT_DIR/chunks.jsonl), chunked by `chunk_book`.
  B   the same text with one newline between paragraphs instead of one space, same chunker.
      The chunk index is identical to A's (one character per break), so only the text differs.
  B2  paragraphs packed whole into chunks of at most 1,200 characters, never crossing a
      paragraph boundary (secondary, exploratory; a long paragraph goes through `chunk_book`).
Gold is remapped per variant by the evidence sentence and first checked to reproduce the
stored gold on A. Nothing here changes the app.

Needs the cached Wikisource pages written by fetch_book.py (OUT_DIR/pages; no download happens
if they exist). Run from the repository root (GPU when torch sees one):
  OUT_DIR=<dir with pages/ and chunks.jsonl> RESULTS=<json> \
  uv run --with sentence-transformers --with scipy --with torch \
    --index https://download.pytorch.org/whl/cu128 python experiments/book-testset/whitespace.py
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import unicodedata
from collections import Counter
from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
import fetch_book as fb

from book_rag.chunking import Chunk, chunk_book
from book_rag.parsing import PageText, ParsedBook, Section

OUT = Path(os.environ.get("OUT_DIR", Path(__file__).parent / "data"))
QUESTIONS = Path(os.environ.get("QUESTIONS", Path(__file__).parent / "questions.jsonl"))
RESULTS = Path(os.environ.get("RESULTS", Path(__file__).parent / "data" / "whitespace.json"))
SEED = 178
TOP_K = 10
CANDIDATES = 30
RRF_K = 60
N_BOOT = 2000
MAX_CHARS = 1200
T_START = time.perf_counter()


def log(msg: str) -> None:
    print(f"[{time.perf_counter() - T_START:7.1f}s] {msg}", flush=True)


TOKEN = re.compile(r"\w+", re.UNICODE)


def tokens(text: str) -> list[str]:
    return TOKEN.findall(text.lower())


def collapse(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


# ---------------------------------------------------------------- the variants
def clean_keep_breaks(text: str) -> str:
    """`fetch_book.clean`, but paragraphs are joined by a newline, not a space."""
    text = unicodedata.normalize("NFC", text).replace("​", "")
    lines = []
    for line in text.splitlines():
        line = re.sub(r"\s+", " ", fb.CJK.sub("", line)).strip()
        if line:
            lines.append(line)
    return "\n".join(lines)


def build_book(keep_breaks: bool) -> ParsedBook:
    sections = []
    for title in fb.CHAPTERS:
        heading, html = fb.fetch(OUT / "pages", title)
        splitter = fb.PageSplitter()
        splitter.feed(html)
        segments = []
        for page, parts in splitter.pages:
            raw = "".join(parts)
            text = clean_keep_breaks(raw)
            if not keep_breaks:
                text = text.replace("\n", " ")
            if text:
                segments.append(PageText(page, text))
        part = title.split("/")[0] if "/" in title else ""
        path = " > ".join(p for p in ("Quyển I", part, heading) if p)
        sections.append(Section(heading, path, 2 if part else 1, tuple(segments)))
    pages = [s.page for sec in sections for s in sec.segments if s.page > 0]
    return ParsedBook("Việt Nam sử lược, Quyển I", max(pages), tuple(sections))


def paragraph_chunks(book: ParsedBook) -> list[Chunk]:
    """B2: pack whole paragraphs up to MAX_CHARS; a longer paragraph is split by `chunk_book`."""
    chunks: list[Chunk] = []

    def emit(section: Section, index: int, text: str, page: int) -> None:
        one = Section(section.title, section.path, section.level, (PageText(page, text),))
        for c in chunk_book(ParsedBook(book.title, book.page_count, (one,))):
            chunks.append(replace(c, ordinal=len(chunks), section_index=index))

    for index, section in enumerate(book.sections):
        pack: list[str] = []
        size = 0
        page = section.segments[0].page
        for segment in section.segments:
            for para in segment.text.split("\n"):
                extra = len(para) + (1 if pack else 0)
                if pack and size + extra > MAX_CHARS:
                    emit(section, index, "\n".join(pack), page)
                    pack, size, page = [], 0, segment.page
                    extra = len(para)
                pack.append(para)
                size += extra
                if size > MAX_CHARS:  # an oversized paragraph stands alone
                    emit(section, index, "\n".join(pack), page)
                    pack, size, page = [], 0, segment.page
        if pack:
            emit(section, index, "\n".join(pack), page)
    return chunks


book_b = build_book(keep_breaks=True)
book_a = build_book(keep_breaks=False)
variants: dict[str, list[Chunk]] = {
    "A": chunk_book(book_a),
    "B": chunk_book(book_b),
    "B2": paragraph_chunks(book_b),
}
stored = [json.loads(x)["text"] for x in (OUT / "chunks.jsonl").read_text("utf-8").splitlines()]
assert [c.text for c in variants["A"]] == stored, "variant A differs from the corpus of #177"
assert [collapse(c.text) for c in variants["A"]] == [collapse(c.text) for c in variants["B"]]
assert all(
    a.text == b.text.replace("\n", " ") for a, b in zip(variants["A"], variants["B"], strict=True)
), "A and B chunks differ by more than the break characters"
newline_chunks = sum("\n" in c.text for c in variants["B"])
log(
    "chunks: "
    + ", ".join(
        f"{v}={len(c)} (mean {np.mean([len(x.text) for x in c]):.0f} chars)"
        for v, c in variants.items()
    )
    + f"; B chunks holding a newline: {newline_chunks}"
)

# ---------------------------------------------------------------- gold by evidence sentence
questions = [json.loads(x) for x in QUESTIONS.read_text("utf-8").splitlines()]
scored = [q for q in questions if q["kind"] != "unanswerable"]
query_sets = {k: [q for q in scored if q["kind"] == k] for k in ("seen", "blind")}


def gold_by_evidence(chunks: list[Chunk], evidence: str) -> list[int]:
    needle = collapse(evidence)
    return [i for i, c in enumerate(chunks) if needle in collapse(c.text)]


golds: dict[str, dict[str, list[int]]] = {}
for name, chunks in variants.items():
    golds[name] = {q["id"]: gold_by_evidence(chunks, q["evidence"]) for q in scored}
mismatch = [q["id"] for q in scored if golds["A"][q["id"]] != q["gold_chunks"]]
if mismatch:
    raise SystemExit(f"evidence rule does not reproduce stored gold on A: {mismatch[:10]}")
assert golds["A"] == golds["B"], "gold differs between A and B"
no_gold_b2 = sorted(qid for qid, g in golds["B2"].items() if not g)
log(
    f"gold remap: A reproduces the stored gold for all {len(scored)} questions; "
    f"B identical to A; B2 has no gold chunk for {len(no_gold_b2)} questions {no_gold_b2[:10]}; "
    f"mean gold chunks A={np.mean([len(g) for g in golds['A'].values()]):.2f} "
    f"B2={np.mean([len(g) for g in golds['B2'].values()]):.2f}"
)

# ---------------------------------------------------------------- retrieval (arm 4)
import torch  # noqa: E402
from scipy import sparse  # noqa: E402
from sentence_transformers import SentenceTransformer  # noqa: E402

DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
log(f"device={DEVICE}")
bge = SentenceTransformer("BAAI/bge-m3", device=DEVICE)
bge.max_seq_length = 1024


def encode(texts: list[str], batch: int) -> np.ndarray:
    return bge.encode(
        texts,
        batch_size=batch,
        normalize_embeddings=True,
        convert_to_numpy=True,
        show_progress_bar=False,
    ).astype(np.float32)


def top_n(scores: np.ndarray, n: int) -> np.ndarray:
    n = min(n, scores.shape[1] - 1)
    part = np.argpartition(-scores, n, axis=1)[:, :n]
    order = np.take_along_axis(scores, part, axis=1).argsort(axis=1)[:, ::-1]
    return np.take_along_axis(part, order, axis=1)


def rrf(rankings: list[list[int]], k: int = RRF_K) -> list[int]:
    scores: dict[int, float] = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking, start=1):
            scores[item] = scores.get(item, 0.0) + 1.0 / (k + rank)
    return [item for item, _ in sorted(scores.items(), key=lambda p: p[1], reverse=True)]


class BM25:
    def __init__(self, docs: list[str], k1: float = 1.2, b: float = 0.75) -> None:
        self.vocab: dict[str, int] = {}
        data, ind, ptr, lengths = [], [], [0], []
        for d in docs:
            counts = Counter(tokens(d))
            lengths.append(sum(counts.values()))
            for t, c in counts.items():
                ind.append(self.vocab.setdefault(t, len(self.vocab)))
                data.append(c)
            ptr.append(len(ind))
        shape = (len(docs), len(self.vocab))
        tf = sparse.csr_matrix((np.array(data, dtype=np.float32), ind, ptr), shape=shape)
        dl = np.array(lengths, dtype=np.float32)
        df = np.bincount(tf.indices, minlength=len(self.vocab))
        idf = np.log(1 + (len(docs) - df + 0.5) / (df + 0.5)).astype(np.float32)
        norm = k1 * (1 - b + b * dl / dl.mean())
        w = tf.tocoo()
        vals = w.data * (k1 + 1) / (w.data + norm[w.row]) * idf[w.col]
        self.weights = sparse.csr_matrix((vals, (w.row, w.col)), shape=shape)

    def scores(self, queries: list[str]) -> np.ndarray:
        data, ind, ptr = [], [], [0]
        for q in queries:
            for t, c in Counter(tokens(q)).items():
                if t in self.vocab:
                    ind.append(self.vocab[t])
                    data.append(c)
            ptr.append(len(ind))
        shape = (len(queries), len(self.vocab))
        qm = sparse.csr_matrix((np.array(data, dtype=np.float32), ind, ptr), shape=shape)
        return np.asarray((qm @ self.weights.T).todense())


def per_query(rankings: list[list[int]], gold: list[list[int]]) -> dict[str, np.ndarray]:
    ranks = []
    for ranked, g in zip(rankings, gold, strict=True):
        top = list(ranked[:TOP_K])
        hits = [top.index(x) + 1 for x in g if x in top]
        ranks.append(min(hits) if hits else 0)
    r = np.array(ranks)
    return {
        "hit@1": (r == 1).astype(float),
        "hit@5": ((r >= 1) & (r <= 5)).astype(float),
        "hit@10": (r >= 1).astype(float),
        "mrr@10": np.where(r > 0, 1.0 / np.maximum(r, 1), 0.0),
    }


def ci(values: np.ndarray, boot_idx: np.ndarray) -> dict[str, float]:
    means = values[boot_idx].mean(axis=1)
    lo, hi = np.percentile(means, [2.5, 97.5])
    return {
        "mean": round(float(values.mean()), 4),
        "lo": round(float(lo), 4),
        "hi": round(float(hi), 4),
    }


embeddings = {v: encode([c.text for c in chunks], 8) for v, chunks in variants.items()}
log("chunks embedded")
cos_ab = (embeddings["A"] * embeddings["B"]).sum(axis=1)
tokens_equal_ab = sum(
    tokens(a.text) == tokens(b.text) for a, b in zip(variants["A"], variants["B"], strict=True)
)
tok_b = [bge.tokenizer(c.text)["input_ids"] for c in variants["B"]]
tok_a = [bge.tokenizer(c.text)["input_ids"] for c in variants["A"]]
bge_tokens_equal = sum(x == y for x, y in zip(tok_a, tok_b, strict=True))
diag = {
    "bm25_token_lists_equal_A_B": f"{tokens_equal_ab}/{len(variants['A'])}",
    "bge_m3_token_ids_equal_A_B": f"{bge_tokens_equal}/{len(variants['A'])}",
    "cosine_A_B_chunk_embedding": {
        "min": round(float(cos_ab.min()), 6),
        "mean": round(float(cos_ab.mean()), 6),
    },
}
log(f"A vs B diagnostics: {json.dumps(diag)}")

ranked: dict[str, dict[str, list[int]]] = {v: {} for v in variants}
for v, chunks in variants.items():
    bm25 = BM25([c.text for c in chunks])
    for rows in query_sets.values():
        texts = [q["question"] for q in rows]
        dense = top_n(encode(texts, 32) @ embeddings[v].T, CANDIDATES).tolist()
        sparse_top = top_n(bm25.scores(texts), CANDIDATES).tolist()
        for q, d, s in zip(rows, dense, sparse_top, strict=True):
            ranked[v][q["id"]] = rrf([d, s])[:TOP_K]
    log(f"variant {v} ranked")

report: dict[str, Any] = {}
for kind, rows in query_sets.items():
    n = len(rows)
    boot = np.random.default_rng(SEED).integers(0, n, size=(N_BOOT, n))
    metrics = {
        v: per_query([ranked[v][q["id"]] for q in rows], [golds[v][q["id"]] for q in rows])
        for v in variants
    }
    same_ranking_ab = sum(ranked["A"][q["id"]] == ranked["B"][q["id"]] for q in rows)
    report[kind] = {
        "n_queries": n,
        "arms": {v: {m: ci(x, boot) for m, x in ms.items()} for v, ms in metrics.items()},
        "paired": {
            f"{a}_minus_A": {
                m: ci(metrics[a][m] - metrics["A"][m], boot)
                for m in ("hit@1", "hit@5", "hit@10", "mrr@10")
            }
            for a in ("B", "B2")
        },
        "questions_with_identical_top10_A_B": f"{same_ranking_ab}/{n}",
    }

results = {
    "issue": 152,
    "arm": "4: bge-m3 + BM25, RRF k=60, no reranker",
    "bootstrap": {"resamples": N_BOOT, "seed": SEED, "interval": "95% percentile"},
    "chunks": {v: len(c) for v, c in variants.items()},
    "mean_chunk_chars": {
        v: round(float(np.mean([len(x.text) for x in c])), 1) for v, c in variants.items()
    },
    "b_chunks_with_newline": newline_chunks,
    "b2_questions_without_gold": no_gold_b2,
    "a_b_diagnostics": diag,
    "query_sets": report,
    "total_s": round(time.perf_counter() - T_START, 1),
    "device": DEVICE,
    "gpu": torch.cuda.get_device_name(0) if DEVICE == "cuda" else None,
    "torch": torch.__version__,
}
RESULTS.parent.mkdir(parents=True, exist_ok=True)
RESULTS.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
print(json.dumps(results, indent=1, ensure_ascii=False))
