import base64
import importlib.util
import io
import json
import subprocess
import zipfile
from pathlib import Path
from types import ModuleType

import pytest

PATH = Path(__file__).resolve().parents[3] / "scripts" / "kaggle_run.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("kaggle_run", PATH)
    assert spec is not None
    assert spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


kaggle_run = _load()


def test_build_embeds_bundle_and_writes_private_gpu_metadata(tmp_path: Path, monkeypatch) -> None:
    prompts = tmp_path / "prompts.jsonl"
    prompts.write_text('{"id": "x"}\n')
    monkeypatch.setattr(kaggle_run, "BUILD", tmp_path / "build")
    out = kaggle_run.build("serving", prompts, "someone")
    meta = json.loads((out / "kernel-metadata.json").read_text())
    assert meta["id"] == "someone/book-rag-serving-bench"
    assert meta["title"].replace(" ", "-") == "book-rag-serving-bench"
    assert meta["is_private"] and meta["enable_gpu"] and meta["enable_internet"]
    script = (out / "script.py").read_text()
    assert "__BUNDLE__" not in script and "__COMMIT__" not in script
    encoded = script.split('BUNDLE = "', 1)[1].split('"', 1)[0]
    names = zipfile.ZipFile(io.BytesIO(base64.b64decode(encoded))).namelist()
    assert sorted(names) == ["concurrency_bench.py", "measure.py", "prompts.jsonl"]
    compile(script, "script.py", "exec")  # the generated kernel is valid Python


def test_limit_keeps_the_first_prompts(tmp_path: Path) -> None:
    prompts = tmp_path / "prompts.jsonl"
    prompts.write_text("".join(f'{{"id": "{x}"}}{chr(10)}' for x in "abc"))
    encoded = kaggle_run.make_bundle({}, prompts, "prompts.jsonl", limit=2)
    bundle = zipfile.ZipFile(io.BytesIO(base64.b64decode(encoded)))
    assert bundle.read("prompts.jsonl").decode().splitlines() == ['{"id": "a"}', '{"id": "b"}']


def test_kernel_runs_only_a_checksummed_ollama() -> None:
    template = kaggle_run.KERNELS["serving"]["template"].read_text(encoding="utf-8")
    assert "install.sh" not in template and "| sh" not in template
    assert "OLLAMA_SHA256" in template and "does not match the pin" in template


def _done(stdout: str = "", code: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess([], code, stdout=stdout)


def test_push_goes_through_the_guard(tmp_path: Path, monkeypatch) -> None:
    calls: list[tuple[str, ...]] = []

    def fake(*args: str, capture: bool = False) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        return _done(code=3)

    monkeypatch.setattr(kaggle_run, "guard", fake)
    assert kaggle_run.push(tmp_path, 60, ["--no-wait"]) == 3
    assert calls[0][:3] == ("push", "-p", str(tmp_path))
    assert calls[0][-3:] == ("--run-timeout", "60", "--no-wait")


def test_missing_guard_pushes_nothing(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(kaggle_run, "GUARD", tmp_path / "absent.py")
    with pytest.raises(SystemExit, match="nothing was pushed"):
        kaggle_run.push(tmp_path, 60, [])


def test_active_versions_reads_this_kernel_only(monkeypatch) -> None:
    out = "RUNNING  me/k version 2\nQUEUED   me/k-05b version 1\n2 active version(s)\n"
    monkeypatch.setattr(kaggle_run, "guard", lambda *a, **k: _done(out))
    assert kaggle_run.active_versions("me/k") == ["RUNNING me/k version 2"]
    monkeypatch.setattr(kaggle_run, "guard", lambda *a, **k: _done("UNKNOWN  me/k: 500\n"))
    assert kaggle_run.active_versions("me/k") is None


def test_wait_goes_on_while_an_older_version_runs(monkeypatch) -> None:
    checks = iter([["RUNNING me/k version 2"], []])
    monkeypatch.setattr(kaggle_run, "status", lambda ref: "cancel")
    monkeypatch.setattr(kaggle_run, "active_versions", lambda ref: next(checks))
    assert kaggle_run.wait("me/k", every=0) == "cancel"
    assert next(checks, None) is None
