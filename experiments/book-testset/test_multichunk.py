"""Unit tests for the Recall@k scoring in multichunk.py (issue #183).

Run one file (not in CI's testpaths):
`uv run --with numpy pytest experiments/book-testset/test_multichunk.py`.
"""

from __future__ import annotations

import sys
from itertools import pairwise
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))

import multichunk as m


def test_found_groups_counts_required_chunks_not_copies() -> None:
    groups = [[1, 2], [10], [20, 21]]  # three required chunks; the first has an overlap copy
    assert m.found_groups([2, 10, 99], groups, 3) == 2
    assert m.found_groups([1, 2, 99], groups, 3) == 1  # two copies of one chunk count once
    assert m.found_groups([99, 98, 97, 1], groups, 3) == 0  # rank 4 is outside k = 3


def test_per_question_recall_hit_all() -> None:
    groups = [[[1], [2]], [[3], [4]]]
    rankings = [[1, 2, 9], [3, 9, 8]]
    per = m.per_question(rankings, groups, 3)
    assert per["recall@3"].tolist() == [1.0, 0.5]
    assert per["hit@3"].tolist() == [1.0, 1.0]
    assert per["all@3"].tolist() == [1.0, 0.0]


def test_recall_is_bounded_by_k_over_required() -> None:
    groups = [[[1], [2], [3], [4]]]
    per = m.per_question([[1, 2, 3, 4]], groups, 2)
    assert per["recall@2"].tolist() == [0.5]  # at most 2 of 4 fit in the top 2


def test_copies_of_finds_overlap_copies() -> None:
    chunks = [
        {"text": "A b c. Câu bằng chứng ở đây. D"},
        {"text": "Câu bằng chứng ở đây. D e f"},
        {"text": "khác hẳn"},
    ]
    assert m.copies_of("câu bằng-chứng ở đây", chunks) == [0, 1]
    assert m.copies_of("", chunks) == []


def test_build_rows_checks_evidence_and_span() -> None:
    chunks = [
        {"text": "alpha beta", "section_path": "S"},
        {"text": "gamma delta", "section_path": "S"},
    ]
    written = [
        {
            "span": 0,
            "question": "q",
            "answer": "a",
            "required": [
                {"chunk": 0, "evidence": "alpha beta"},
                {"chunk": 1, "evidence": "not in the chunk"},
            ],
        }
    ]
    rows, problems = m.build_rows(written, [[0, 1]], chunks)
    assert rows[0]["gold_groups"] == [[0], []]
    assert any("evidence not in chunk 1" in p for p in problems)


def test_draw_spans_rules() -> None:
    chunks = [
        {"text": "x" * 400, "section_path": f"S{i // 12}", "section_index": i // 12}
        for i in range(60)
    ]
    spans = m.draw_spans(chunks, seed=1, n=10)
    flat = [c for s in spans for c in s]
    assert len(flat) == len(set(flat))  # no chunk reused
    for s in spans:
        assert len({chunks[c]["section_index"] for c in s}) == 1  # one section
        assert all(b - a >= m.MIN_GAP for a, b in pairwise(s))


def test_bm25_ranks_matching_chunk_first_and_bootstrap_is_seeded() -> None:
    docs = ["con rồng cháu tiên", "đánh quân nguyên mông", "ruộng đất thuế má"]
    assert m.BM25(docs).rank("quân nguyên")[0] == 1
    a = m.boot_indices(5)
    assert np.array_equal(a, m.boot_indices(5))
    iv = m.interval(np.array([1.0, 0.0, 1.0, 0.0, 1.0]), a)
    assert iv["lo"] <= iv["mean"] <= iv["hi"]
