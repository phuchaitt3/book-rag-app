"""The alert rules, runbook, SLO doc and dashboard agree with each other and `metrics.py` (#226).

The structural tests are pure Python (the rules file is read with regexes, so no YAML library is
needed). The promtool test runs the real rule checker through the Prometheus image and skips when
Docker is not available.
"""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
OPS = ROOT / "docs" / "operations"
METRICS_PY = ROOT / "apps" / "api" / "src" / "book_rag_api" / "metrics.py"
PROMETHEUS_IMAGE = "prom/prometheus:v2.55.1"

# Series Prometheus itself creates for every scrape target.
STANDARD_METRICS = {"up", "scrape_duration_seconds", "process_cpu_seconds_total"}
PROMQL_WORDS = {"by", "without", "on", "ignoring", "and", "or", "unless", "bool"}


def exported_series() -> set[str]:
    """Series names `/metrics` serves, from the metric definitions in metrics.py."""
    text = METRICS_PY.read_text(encoding="utf-8")
    names: set[str] = set()
    for kind, name in re.findall(r"\b(Histogram|Counter)\(\s*\"([a-z_]+)\"", text):
        if kind == "Histogram":
            names |= {f"{name}_bucket", f"{name}_count", f"{name}_sum"}
        else:
            names.add(f"{name}_total")
    return names


def referenced_series(expr: str) -> set[str]:
    """Metric names in a PromQL expression: an identifier right before `{` or a `[range]`."""
    without_strings = re.sub(r'"[^"]*"', '""', expr)
    # Label selectors `{...}` hold no metric names; drop them but keep the name before them.
    names = re.findall(r"\b([a-zA-Z_:][a-zA-Z0-9_:]*)\s*(?=\{|\[)", without_strings)
    return {n for n in names if n not in PROMQL_WORDS}


def alert_blocks() -> list[tuple[str, str]]:
    """(alert name, expr text) for each rule in alerts.yml."""
    text = (OPS / "alerts.yml").read_text(encoding="utf-8")
    blocks = re.split(r"^\s*- alert: ", text, flags=re.MULTILINE)[1:]
    result = []
    for block in blocks:
        name = block.splitlines()[0].strip()
        match = re.search(r"^\s*expr: \|\n((?:\s{10,}.*\n?)+)", block, re.MULTILINE)
        if match is None:
            match = re.search(r"^\s*expr: (.+)$", block, re.MULTILINE)
        assert match, f"alert {name} has no expr"
        result.append((name, match.group(1)))
    return result


def test_alerts_file_has_the_expected_shape() -> None:
    text = (OPS / "alerts.yml").read_text(encoding="utf-8")
    assert "\t" not in text, "YAML must not contain tabs"
    assert re.search(r"^groups:\n", text, re.MULTILINE)
    blocks = alert_blocks()
    names = [name for name, _ in blocks]
    assert len(blocks) >= 6
    assert len(set(names)) == len(names), "duplicate alert names"
    # Every rule carries a severity and a summary; brackets and parentheses balance.
    assert text.count("severity:") == len(blocks)
    assert text.count("summary:") == len(blocks)
    for name, expr in blocks:
        assert expr.count("(") == expr.count(")"), f"{name}: unbalanced parentheses"
        assert expr.count("{") == expr.count("}"), f"{name}: unbalanced braces"
        assert expr.count("[") == expr.count("]"), f"{name}: unbalanced brackets"


def test_every_alert_has_a_runbook_entry() -> None:
    runbook = (OPS / "runbook.md").read_text(encoding="utf-8")
    entries = set(re.findall(r"^## (\w+)$", runbook, re.MULTILINE))
    alerts = {name for name, _ in alert_blocks()}
    assert alerts - entries == set(), "alerts without a runbook entry"
    assert entries - alerts == set(), "runbook entries without an alert"
    # The runbook link in each alert points at its own anchor.
    text = (OPS / "alerts.yml").read_text(encoding="utf-8")
    for name in alerts:
        assert f"docs/operations/runbook.md#{name.lower()}" in text


def test_every_referenced_metric_is_exported() -> None:
    exported = exported_series()
    assert "http_request_duration_seconds_count" in exported  # the parser found the definitions
    for name, expr in alert_blocks():
        unknown = referenced_series(expr) - exported - STANDARD_METRICS
        assert unknown == set(), f"alert {name} uses metrics the API does not export: {unknown}"


def test_dashboard_is_valid_json_and_uses_exported_metrics() -> None:
    dashboard = json.loads((OPS / "grafana" / "book-rag.json").read_text(encoding="utf-8"))
    assert dashboard["uid"] == "book-rag"
    assert len(dashboard["panels"]) >= 5
    exported = exported_series()
    for panel in dashboard["panels"]:
        for target in panel["targets"]:
            unknown = referenced_series(target["expr"]) - exported - STANDARD_METRICS
            assert unknown == set(), f"panel {panel['title']}: {unknown}"


def test_slo_doc_cites_the_benchmark_and_the_benchmark_exists() -> None:
    slo = (OPS / "slo.md").read_text(encoding="utf-8")
    assert "serving-latency.md" in slo
    assert (ROOT / "docs" / "benchmarks" / "serving-latency.md").is_file()


def test_observability_compose_binds_ports_to_loopback() -> None:
    text = (ROOT / "compose.observability.yaml").read_text(encoding="utf-8")
    ports = re.findall(r'^\s*- "([^"]+:\d+:\d+)"', text, re.MULTILINE)
    assert ports, "no published ports found"
    assert all(p.startswith("127.0.0.1:") for p in ports), ports


def docker_available() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        return subprocess.run(["docker", "info"], capture_output=True, timeout=30).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


@pytest.mark.skipif(not docker_available(), reason="Docker is not available")
def test_promtool_accepts_the_alert_rules() -> None:
    result = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "-v",
            f"{OPS}:/rules:ro",
            "--entrypoint",
            "promtool",
            PROMETHEUS_IMAGE,
            "check",
            "rules",
            "/rules/alerts.yml",
        ],
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert result.returncode == 0, result.stdout + result.stderr
