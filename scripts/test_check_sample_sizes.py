from pathlib import Path

import check_sample_sizes as cs


def test_readme_hit_rate_without_sample_size_fails() -> None:
    assert cs.check_text("# App\n\nThe search has a 92% hit rate.\n") == [
        (3, "The search has a 92% hit rate.")
    ]


def test_sample_size_in_same_section_passes() -> None:
    assert cs.check_text("# A\n\n92% hit rate (n=208).\n") == []
    assert cs.check_text("# A\n\nOn 40 queries:\n\n| p50 | 120 ms |\n") == []
    assert cs.check_text("# A\n\n208 blind questions give 88.9% Hit@5.\n") == []


def test_sample_size_in_another_section_does_not_count() -> None:
    assert cs.check_text("# A\n\n## S1\n\nn=100\n\n## S2\n\n120 ms\n") == [(9, "120 ms")]


def test_waiver_passes_section() -> None:
    assert cs.check_text("# A\n\n<!-- numcheck: ok: a target -->\nUnder 120 ms.\n") == []


def test_latency_and_metric_claims() -> None:
    assert cs.check_text("# A\n\nMedian 1.5 seconds.\n")
    assert cs.check_text("# A\n\nrecall@5 = 0.83\n")


def test_ci_level_code_and_plain_numbers_are_ignored() -> None:
    text = "# A\n\n95% CI of the mean, 3 retries, port 8000.\n\n```\n99% 10 ms\n```\n"
    assert cs.check_text(text) == []


def test_run_exit_code(tmp_path: Path) -> None:
    bad = tmp_path / "README.md"
    bad.write_text("# A\n\n92% hit rate\n", encoding="utf-8")
    ok = tmp_path / "ok.md"
    ok.write_text("# A\n\n92% hit rate, n=10\n", encoding="utf-8")
    assert cs.run([ok], tmp_path) == 0
    assert cs.run([bad], tmp_path) == 1


def test_default_scope(tmp_path: Path) -> None:
    names = ("README.md", "docs/a.md", "docs/benchmarks/b.md", "docs/adr/c.md")
    for rel in (*names, "docs/design/d.md", "docs/operations/e.md"):
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x", encoding="utf-8")
    shown = [p.relative_to(tmp_path).as_posix() for p in cs.default_files(tmp_path)]
    assert shown == ["README.md", "docs/a.md", "docs/benchmarks/b.md"]


def test_repository_passes() -> None:
    root = Path(__file__).resolve().parent.parent
    assert cs.run(cs.default_files(root), root) == 0
